#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "json"
require "optparse"
require "time"

DEFAULT_OPTIONS = {
  "input" => "data/canonical-items/latest.json",
  "store_dir" => "data/store",
  "date" => nil
}.freeze

def parse_options(argv)
  options = DEFAULT_OPTIONS.dup

  OptionParser.new do |opts|
    opts.banner = "Usage: src/store_canonical_jsonl.rb [options]"
    opts.on("--input PATH", "Canonical items JSON path") { |value| options["input"] = value }
    opts.on("--store-dir PATH", "Store directory") { |value| options["store_dir"] = value }
    opts.on("--date YYYY-MM-DD", "Store partition date") { |value| options["date"] = value }
  end.parse!(argv)

  options
end

def present?(value)
  !(value.nil? || value.to_s.strip.empty?)
end

def partition_date(options)
  value = options["date"]
  return value if present?(value)

  Time.now.strftime("%Y-%m-%d")
end

def jsonl_existing_ids(path)
  return {} unless File.exist?(path)

  ids = {}
  File.foreach(path).with_index(1) do |line, line_number|
    next if line.strip.empty?

    record = JSON.parse(line)
    id = record["id"]
    ids[id] = line_number if present?(id)
  end
  ids
end

def validate_item!(item, index)
  required = %w[id source_id source_type provider title fetched_at content_hash dedupe_key]
  missing = required.reject { |field| present?(item[field]) }
  raise "item #{index} missing required fields: #{missing.join(", ")}" unless missing.empty?
end

def append_jsonl(path, records)
  return if records.empty?

  FileUtils.mkdir_p(File.dirname(path))
  File.open(path, "a") do |file|
    records.each do |record|
      file.write(JSON.generate(record))
      file.write("\n")
    end
  end
end

def store(canonical, options)
  date = partition_date(options)
  store_dir = options["store_dir"]
  items_path = File.join(store_dir, "items", "#{date}.jsonl")
  runs_path = File.join(store_dir, "runs", "#{date}.jsonl")
  stored_at = Time.now.iso8601

  items = canonical.fetch("items")
  existing_ids = jsonl_existing_ids(items_path)
  appended = []
  skipped = []

  items.each_with_index do |item, index|
    validate_item!(item, index)

    if existing_ids.key?(item.fetch("id"))
      skipped << {
        "id" => item.fetch("id"),
        "source_id" => item.fetch("source_id"),
        "reason" => "duplicate_id",
        "existing_line" => existing_ids[item.fetch("id")]
      }
      next
    end

    appended << item.merge(
      "stored_at" => stored_at,
      "store_partition" => date,
      "input_run_id" => canonical["run_id"]
    )
    existing_ids[item.fetch("id")] = existing_ids.length + appended.length
  end

  append_jsonl(items_path, appended)

  run_record = {
    "stored_at" => stored_at,
    "store_partition" => date,
    "input_run_id" => canonical["run_id"],
    "input_adapter" => canonical["input_adapter"],
    "items_path" => items_path,
    "input_items" => items.length,
    "appended_items" => appended.length,
    "skipped_duplicates" => skipped.length,
    "dropped_items" => canonical.dig("summary", "dropped_items"),
    "skipped" => skipped
  }
  append_jsonl(runs_path, [run_record])

  {
    "items_path" => items_path,
    "runs_path" => runs_path,
    "input_items" => items.length,
    "appended_items" => appended.length,
    "skipped_duplicates" => skipped.length
  }
end

def main(argv)
  options = parse_options(argv)
  canonical = JSON.parse(File.read(options["input"]))
  summary = store(canonical, options)

  puts JSON.pretty_generate(summary)
end

main(ARGV)
