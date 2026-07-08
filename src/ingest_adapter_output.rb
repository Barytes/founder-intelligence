#!/usr/bin/env ruby
# frozen_string_literal: true

require "cgi"
require "digest"
require "fileutils"
require "json"
require "optparse"
require "time"
require "uri"
require "yaml"

DEFAULT_OPTIONS = {
  "input" => "data/adapter-output/rss-fetch-latest.json",
  "sources" => "config/sources.yml",
  "rules" => "config/ingestion-rules.yml",
  "output" => "data/canonical-items/latest.json"
}.freeze

def parse_options(argv)
  options = DEFAULT_OPTIONS.dup

  OptionParser.new do |opts|
    opts.banner = "Usage: src/ingest_adapter_output.rb [options]"
    opts.on("--input PATH", "Adapter output JSON path") { |value| options["input"] = value }
    opts.on("--sources PATH", "Path to config/sources.yml") { |value| options["sources"] = value }
    opts.on("--rules PATH", "Path to config/ingestion-rules.yml") { |value| options["rules"] = value }
    opts.on("--output PATH", "Canonical items JSON output path") { |value| options["output"] = value }
  end.parse!(argv)

  options
end

def present?(value)
  !(value.nil? || value.to_s.strip.empty?)
end

def clean_text(value, strip_html:, collapse_whitespace:)
  return nil unless present?(value)

  text = value.to_s
  if strip_html
    text = text.gsub(%r{<\s*br\s*/?\s*>}i, "\n")
    text = text.gsub(%r{</\s*p\s*>}i, "\n")
    text = text.gsub(/<[^>]*>/, " ")
    text = CGI.unescapeHTML(text)
  end
  text = text.gsub(/\s+/, " ") if collapse_whitespace
  text.strip
end

def truncate_text(value, max_chars)
  return value unless present?(value) && max_chars.to_i.positive?

  value.length > max_chars ? value[0, max_chars] : value
end

def normalize_datetime(value)
  return nil unless present?(value)

  Time.parse(value.to_s).iso8601
rescue ArgumentError
  nil
end

def normalize_link(value, remove_params)
  return nil unless present?(value)

  uri = URI.parse(value.to_s.strip)
  return value.to_s.strip unless %w[http https].include?(uri.scheme)

  if present?(uri.query)
    params = URI.decode_www_form(uri.query).reject do |key, _|
      remove_params.include?(key)
    end
    uri.query = params.empty? ? nil : URI.encode_www_form(params)
  end

  uri.fragment = nil
  uri.to_s
rescue URI::InvalidURIError
  value.to_s.strip
end

def source_map(sources_config)
  sources_config.fetch("sources").each_with_object({}) do |source, map|
    map[source.fetch("id")] = source
  end
end

def content_hash_for(item, fields)
  payload = fields.map { |field| item[field] }.compact.join("\n")
  Digest::SHA256.hexdigest(payload)
end

def compact_hash(hash)
  hash.each_with_object({}) do |(key, value), result|
    next if value.nil?
    next if value.respond_to?(:empty?) && value.empty?

    result[key] = value
  end
end

def source_title_published_at(item)
  [item["source_id"], item["title"], item["published_at"]].compact.join("|")
end

def build_dedupe_keys(item, strategies)
  keys = {}

  strategies.each do |strategy|
    case strategy
    when "platform_item_id"
      keys[strategy] = item["platform_item_id"] if present?(item["platform_item_id"])
    when "guid"
      keys[strategy] = item["guid"] if present?(item["guid"])
    when "normalized_link"
      keys[strategy] = item["normalized_link"] if present?(item["normalized_link"])
    when "source_id_title_published_at"
      value = source_title_published_at(item)
      keys[strategy] = value if present?(value)
    when "content_hash"
      keys[strategy] = item["content_hash"] if present?(item["content_hash"])
    when "author_title_content_hash"
      value = [item["author"], item["title"], item["content_hash"]].compact.join("|")
      keys[strategy] = value if present?(value)
    end
  end

  keys
end

def primary_dedupe_key(dedupe_keys, strategies)
  strategies.each do |strategy|
    value = dedupe_keys[strategy]
    return "#{strategy}:#{value}" if present?(value)
  end

  nil
end

def canonical_item(raw_item, source, adapter_result, rules)
  normalization = rules.fetch("normalization")
  strip_html = normalization["strip_html"] == true
  collapse_whitespace = normalization["collapse_whitespace"] == true
  remove_params = normalization.fetch("remove_tracking_params", [])
  max_summary_chars = normalization.fetch("max_summary_chars", 0)
  max_content_chars = normalization.fetch("max_content_chars", 0)

  title = clean_text(raw_item["title"], strip_html: strip_html, collapse_whitespace: collapse_whitespace)
  summary = clean_text(raw_item["summary"], strip_html: strip_html, collapse_whitespace: collapse_whitespace)
  content = clean_text(raw_item["content"], strip_html: strip_html, collapse_whitespace: collapse_whitespace)
  normalized_link = normalize_link(raw_item["link"], remove_params)
  published_at = normalize_datetime(raw_item["published_at"])
  fetched_at = normalize_datetime(adapter_result["fetched_at"]) || adapter_result["fetched_at"]

  item = compact_hash(
    "source_id" => adapter_result.fetch("source_id"),
    "source_type" => adapter_result.fetch("source_type"),
    "provider" => adapter_result.fetch("provider"),
    "source_name" => source["name"],
    "fetcher" => source["fetcher"],
    "platform_item_id" => raw_item["platform_item_id"],
    "guid" => raw_item["guid"],
    "title" => title,
    "link" => raw_item["link"],
    "normalized_link" => normalized_link,
    "published_at" => published_at,
    "fetched_at" => fetched_at,
    "author" => clean_text(raw_item["author"], strip_html: strip_html, collapse_whitespace: collapse_whitespace),
    "summary" => truncate_text(summary, max_summary_chars),
    "content" => truncate_text(content, max_content_chars),
    "category" => source["category"],
    "tags" => source["tags"],
    "priority" => source["priority"],
    "raw" => normalization["preserve_raw_payload"] ? raw_item["raw"] : nil
  )

  hash_fields = rules.dig("deduplication", "content_hash", "fields") || %w[title normalized_link summary content]
  item["content_hash"] = content_hash_for(item, hash_fields)

  strategies = rules.dig("deduplication", "provider_overrides", item["provider"]) ||
               rules.dig("deduplication", "provider_overrides", item["source_type"]) ||
               rules.dig("deduplication", "global_strategy") ||
               %w[platform_item_id guid normalized_link content_hash]
  item["dedupe_keys"] = build_dedupe_keys(item, strategies)
  item["dedupe_key"] = primary_dedupe_key(item["dedupe_keys"], strategies)
  item["id"] = Digest::SHA256.hexdigest(item["dedupe_key"] || item["content_hash"])

  item
end

def quality_flags(item, rules)
  flags = []
  gates = rules.fetch("quality_gates", {})
  flag_when = gates.fetch("flag_item_when", {})

  flags << "content_empty" if flag_when["content_empty"] && !present?(item["content"])
  flags << "published_at_empty" if flag_when["published_at_empty"] && !present?(item["published_at"])
  flags << "author_empty" if flag_when["author_empty"] && !present?(item["author"])

  flags
end

def should_drop_title_empty?(item, rules)
  rules.dig("quality_gates", "drop_item_when", "title_empty") == true && !present?(item["title"])
end

def required_fields_valid?(item, rules)
  required = rules.dig("canonical_item", "required_fields") || []
  required.all? { |field| present?(item[field]) }
end

def ingest(adapter_output, sources_config, rules)
  sources = source_map(sources_config)
  seen = {}
  canonical_items = []
  dropped_items = []

  adapter_output.fetch("results").each do |result|
    source = sources[result.fetch("source_id")]
    unless source
      dropped_items << {
        "source_id" => result["source_id"],
        "reason" => "source_not_found"
      }
      next
    end

    result.fetch("items").each do |raw_item|
      item = canonical_item(raw_item, source, result, rules)
      item["quality_flags"] = quality_flags(item, rules)

      if should_drop_title_empty?(item, rules)
        dropped_items << { "raw_id" => raw_item["raw_id"], "source_id" => item["source_id"], "reason" => "title_empty" }
        next
      end

      unless required_fields_valid?(item, rules)
        dropped_items << { "raw_id" => raw_item["raw_id"], "source_id" => item["source_id"], "reason" => "required_fields_missing" }
        next
      end

      dedupe_key = item["dedupe_key"]
      if dedupe_key && seen.key?(dedupe_key)
        dropped_items << {
          "raw_id" => raw_item["raw_id"],
          "source_id" => item["source_id"],
          "reason" => "duplicate",
          "duplicate_of" => seen[dedupe_key]
        }
        next
      end

      seen[dedupe_key] = item["id"] if dedupe_key
      canonical_items << item
    end
  end

  {
    "run_id" => adapter_output["run_id"],
    "input_adapter" => adapter_output["adapter"],
    "contract_version" => 1,
    "ingested_at" => Time.now.iso8601,
    "summary" => {
      "input_results" => adapter_output.fetch("results").length,
      "canonical_items" => canonical_items.length,
      "dropped_items" => dropped_items.length
    },
    "items" => canonical_items,
    "dropped_items" => dropped_items
  }
end

def validate_output!(output, rules)
  required = rules.dig("canonical_item", "required_fields") || []
  output.fetch("items").each_with_index do |item, index|
    missing = required.reject { |field| present?(item[field]) }
    raise "canonical item #{index} missing required fields: #{missing.join(", ")}" unless missing.empty?
    raise "canonical item #{index} missing content_hash" unless present?(item["content_hash"])
    raise "canonical item #{index} missing dedupe_key" unless present?(item["dedupe_key"])
  end
end

def main(argv)
  options = parse_options(argv)
  adapter_output = JSON.parse(File.read(options["input"]))
  sources_config = YAML.load_file(options["sources"])
  rules = YAML.load_file(options["rules"])

  output = ingest(adapter_output, sources_config, rules)
  validate_output!(output, rules)

  FileUtils.mkdir_p(File.dirname(options["output"]))
  File.write(options["output"], "#{JSON.pretty_generate(output)}\n")
end

main(ARGV)
