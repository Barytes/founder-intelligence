#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"
require "fileutils"
require "json"
require "net/http"
require "optparse"
require "rexml/document"
require "securerandom"
require "time"
require "uri"
require "yaml"

DEFAULT_OPTIONS = {
  "sources" => "config/sources.yml",
  "rules" => "config/ingestion-rules.yml",
  "output" => nil,
  "source_id" => nil,
  "max_items" => nil
}.freeze

STATUS_VALUES = %w[ok partial failed skipped].freeze
RESPONSE_REQUIRED_FIELDS = %w[
  source_id
  source_type
  provider
  fetched_at
  status
  items
  errors
].freeze

def parse_options(argv)
  options = DEFAULT_OPTIONS.dup

  OptionParser.new do |opts|
    opts.banner = "Usage: src/fetch_rss.rb [options]"
    opts.on("--sources PATH", "Path to config/sources.yml") { |value| options["sources"] = value }
    opts.on("--rules PATH", "Path to config/ingestion-rules.yml") { |value| options["rules"] = value }
    opts.on("--source-id ID", "Fetch only one source id") { |value| options["source_id"] = value }
    opts.on("--max-items N", Integer, "Maximum items per source") { |value| options["max_items"] = value }
    opts.on("--output PATH", "Write JSON output to path") { |value| options["output"] = value }
  end.parse!(argv)

  options
end

def now_iso8601
  Time.now.iso8601
end

def present?(value)
  !(value.nil? || value.to_s.strip.empty?)
end

def clean_text(value)
  return nil unless present?(value)

  value.to_s.gsub(/\s+/, " ").strip
end

def child_text(element, *names)
  candidates = names.map(&:to_s)

  element.elements.each do |child|
    qname = [child.prefix, child.name].compact.join(":")
    if candidates.include?(child.name) || candidates.include?(qname) || candidates.include?(child.expanded_name)
      return clean_text(child.text)
    end
  end

  nil
end

def child_values(element, *names)
  candidates = names.map(&:to_s)
  values = []

  element.elements.each do |child|
    qname = [child.prefix, child.name].compact.join(":")
    next unless candidates.include?(child.name) || candidates.include?(qname) || candidates.include?(child.expanded_name)

    value = clean_text(child.text)
    values << value if present?(value)
  end

  values
end

def atom_link(entry)
  entry.elements.each("link") do |link|
    href = link.attributes["href"]
    rel = link.attributes["rel"]
    return href if present?(href) && (!present?(rel) || rel == "alternate")
  end

  nil
end

def fetch_xml(url, timeout_seconds, user_agent)
  uri = URI.parse(url)
  raise ArgumentError, "unsupported URI scheme: #{uri.scheme}" unless %w[http https].include?(uri.scheme)

  request = Net::HTTP::Get.new(uri)
  request["User-Agent"] = user_agent if present?(user_agent)

  response = Net::HTTP.start(
    uri.host,
    uri.port,
    use_ssl: uri.scheme == "https",
    open_timeout: timeout_seconds,
    read_timeout: timeout_seconds
  ) do |http|
    http.request(request)
  end

  unless response.is_a?(Net::HTTPSuccess)
    raise "HTTP #{response.code} from #{url}"
  end

  [response.body, response]
end

def parse_rss_items(doc, source_id, max_items)
  items = REXML::XPath.match(doc, "//item").first(max_items)

  items.each_with_index.map do |item, index|
    guid = child_text(item, "guid")
    link = child_text(item, "link")
    title = child_text(item, "title") || link || guid || "(untitled)"
    raw_key = [guid, link, title, index].find { |value| present?(value) }

    {
      "raw_id" => "rss:#{source_id}:#{Digest::SHA256.hexdigest(raw_key.to_s)[0, 16]}",
      "platform_item_id" => guid || link,
      "guid" => guid,
      "title" => title,
      "link" => link,
      "published_at" => child_text(item, "pubDate", "published", "updated", "date", "dc:date"),
      "author" => child_text(item, "author", "creator", "dc:creator"),
      "summary" => child_text(item, "description", "summary"),
      "content" => child_text(item, "content:encoded", "encoded", "content", "description"),
      "categories" => child_values(item, "category"),
      "raw" => {
        "source_format" => "rss",
        "guid" => guid,
        "link" => link
      }
    }.compact
  end
end

def parse_atom_items(doc, source_id, max_items)
  entries = doc.root.elements.select { |element| element.name == "entry" }.first(max_items)

  entries.each_with_index.map do |entry, index|
    guid = child_text(entry, "id")
    link = atom_link(entry)
    title = child_text(entry, "title") || link || guid || "(untitled)"
    raw_key = [guid, link, title, index].find { |value| present?(value) }

    {
      "raw_id" => "rss:#{source_id}:#{Digest::SHA256.hexdigest(raw_key.to_s)[0, 16]}",
      "platform_item_id" => guid || link,
      "guid" => guid,
      "title" => title,
      "link" => link,
      "published_at" => child_text(entry, "published", "updated"),
      "author" => child_text(entry, "author", "name"),
      "summary" => child_text(entry, "summary"),
      "content" => child_text(entry, "content", "summary"),
      "categories" => entry.elements.select { |element| element.name == "category" }.map { |category| category.attributes["term"] }.compact,
      "raw" => {
        "source_format" => "atom",
        "guid" => guid,
        "link" => link
      }
    }.compact
  end
end

def parse_feed(xml, source_id, max_items)
  doc = REXML::Document.new(xml)
  root_name = doc.root&.name

  if root_name == "feed"
    [parse_atom_items(doc, source_id, max_items), { "format" => "atom", "title" => child_text(doc.root, "title") }]
  else
    channel = REXML::XPath.first(doc, "//channel")
    metadata = {
      "format" => "rss",
      "title" => channel ? child_text(channel, "title") : nil,
      "link" => channel ? child_text(channel, "link") : nil,
      "description" => channel ? child_text(channel, "description") : nil
    }.compact
    [parse_rss_items(doc, source_id, max_items), metadata]
  end
end

def error_payload(code:, message:, retryable:, item_scope:, raw_status: nil)
  {
    "code" => code,
    "message" => message.to_s,
    "retryable" => retryable,
    "item_scope" => item_scope,
    "raw_status" => raw_status
  }.compact
end

def fetch_source(source, rules, context)
  source_id = source.fetch("id")
  fetched_at = now_iso8601
  connection = source.fetch("connection")
  timeout = source.dig("timeout_seconds") || rules.dig("fetch", "timeout_seconds") || 20
  max_items = context["max_items"] || rules.dig("fetch", "max_items_per_source") || 50
  user_agent = rules.dig("fetch", "user_agent")

  response = {
    "source_id" => source_id,
    "source_type" => source.fetch("source_type"),
    "provider" => source.fetch("provider"),
    "fetched_at" => fetched_at,
    "status" => "failed",
    "items" => [],
    "errors" => []
  }

  unless connection["rss_url"]
    response["errors"] << error_payload(
      code: "invalid_config",
      message: "rss source requires connection.rss_url",
      retryable: false,
      item_scope: "source"
    )
    return response
  end

  begin
    xml, http_response = fetch_xml(connection["rss_url"], timeout, user_agent)
    items, metadata = parse_feed(xml, source_id, max_items)
    response["status"] = "ok"
    response["items"] = items
    response["raw_feed_metadata"] = metadata
    response["rate_limit"] = {
      "limit" => http_response["x-ratelimit-limit"],
      "remaining" => http_response["x-ratelimit-remaining"],
      "reset_at" => http_response["x-ratelimit-reset"],
      "retry_after_seconds" => http_response["retry-after"]
    }.compact
  rescue REXML::ParseException => e
    response["errors"] << error_payload(
      code: "invalid_xml",
      message: e.message.lines.first,
      retryable: false,
      item_scope: "source"
    )
  rescue StandardError => e
    response["errors"] << error_payload(
      code: "rss_url_unreachable",
      message: e.message,
      retryable: true,
      item_scope: "source"
    )
  end

  response
end

def validate_response!(response)
  missing = RESPONSE_REQUIRED_FIELDS.reject { |field| response.key?(field) }
  raise "adapter response missing fields: #{missing.join(", ")}" unless missing.empty?
  raise "invalid adapter status: #{response["status"]}" unless STATUS_VALUES.include?(response["status"])
  raise "items must be an array" unless response["items"].is_a?(Array)
  raise "errors must be an array" unless response["errors"].is_a?(Array)

  response["items"].each_with_index do |item, index|
    raise "item #{index} missing raw_id" unless present?(item["raw_id"])
    raise "item #{index} missing title" unless present?(item["title"])
  end
end

def main(argv)
  options = parse_options(argv)
  sources_config = YAML.load_file(options["sources"])
  rules = YAML.load_file(options["rules"])
  run_id = "rss-fetch-#{Time.now.utc.strftime("%Y%m%dT%H%M%SZ")}-#{SecureRandom.hex(4)}"

  rss_sources = sources_config.fetch("sources").select do |source|
    source["enabled"] != false && source["source_type"] == "rss"
  end
  rss_sources = rss_sources.select { |source| source["id"] == options["source_id"] } if options["source_id"]

  context = {
    "run_id" => run_id,
    "fetched_at" => now_iso8601,
    "max_items" => options["max_items"]
  }.compact

  results = rss_sources.map { |source| fetch_source(source, rules, context) }
  results.each { |response| validate_response!(response) }

  output = {
    "run_id" => run_id,
    "adapter" => "rss",
    "contract_version" => 1,
    "fetched_at" => context["fetched_at"],
    "results" => results
  }

  json = JSON.pretty_generate(output)
  if options["output"]
    FileUtils.mkdir_p(File.dirname(options["output"]))
    File.write(options["output"], "#{json}\n")
  else
    puts json
  end
end

main(ARGV)
