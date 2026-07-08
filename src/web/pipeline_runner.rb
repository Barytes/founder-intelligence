# frozen_string_literal: true

require "fileutils"
require "json"
require "open3"
require "rbconfig"
require "securerandom"
require "time"
require "timeout"

module FounderIntelligence
  module Web
    class PipelineRunner
      SENSITIVE_PATTERN = /(GITHUB_ACCESS_TOKEN|authorization|token)(\s*[:=]\s*)[^\s,;]+/i.freeze

      def initialize(root:, commands: nil, timeout_seconds: 120)
        @root = File.expand_path(root)
        @commands = commands || default_commands
        @timeout_seconds = timeout_seconds
        @request_id = nil
        @current_run_id = nil
        @run_started_at = nil
        @store_summary = nil
        @signal_diff = nil
        @step_results = []
      end

      def refresh
        FileUtils.mkdir_p(app_dir)
        lock_result = acquire_lock
        return lock_result unless lock_result.fetch("status") == "locked"

        @request_id = lock_result.fetch("request_id")
        @step_results = []
        @store_summary = nil
        @signal_diff = nil
        @run_started_at = Time.now
        write_status("running", "current_step" => nil, "command_results" => [])

        begin
          @commands.each do |command|
            run_step(command)
            validate_step(command.fetch("name"))
          end
          publish_signals
          cleanup_temp_dirs
        rescue StandardError => error
          status = write_status(
            "failed",
            "last_error" => redact(error.message),
            "command_results" => @step_results
          )
          release_lock
          return status
        end

        signal_count = parsed_temp_signals.fetch("signals", []).length
        status_name = signal_count.positive? ? "succeeded" : "succeeded_empty"
        status = write_status(
          status_name,
          "command_results" => @step_results,
          "last_successful_generated_at" => parsed_temp_signals["generated_at"],
          "last_successful_input_run_id" => parsed_temp_signals["input_run_id"]
        )
        release_lock
        status
      end

      private

      def default_commands
        ruby = RbConfig.ruby
        [
          {
            "name" => "fetch_rss",
            "argv" => [ruby, "src/fetch_rss.rb", "--output", "data/adapter-output/rss-fetch-latest.json"]
          },
          {
            "name" => "ingest_adapter_output",
            "argv" => [
              ruby,
              "src/ingest_adapter_output.rb",
              "--input",
              "data/adapter-output/rss-fetch-latest.json",
              "--output",
              "data/canonical-items/latest.json"
            ]
          },
          {
            "name" => "store_canonical_jsonl",
            "argv" => [
              ruby,
              "src/store_canonical_jsonl.rb",
              "--input",
              "data/canonical-items/latest.json",
              "--store-dir",
              "data/store"
            ]
          },
          {
            "name" => "build_signals",
            "argv" => [
              ruby,
              "src/build_signals.rb",
              "--input",
              "data/canonical-items/latest.json",
              "--profile",
              "config/user-profile.yml",
              "--rules",
              "config/signal-rules.yml",
              "--output",
              temp_signals_relative_path,
              "--markdown",
              temp_markdown_relative_path,
              "--html",
              temp_html_relative_path
            ]
          }
        ]
      end

      def acquire_lock
        if File.exist?(lock_path)
          lock = parse_json_file(lock_path)
          return mark_stale_lock unless process_alive?(lock["pid"])

          return { "status" => "already_running", "request_id" => lock["request_id"] }
        end

        request_id = "refresh-#{Time.now.utc.strftime('%Y%m%dT%H%M%SZ')}-#{SecureRandom.hex(4)}"
        lock = {
          "request_id" => request_id,
          "pid" => Process.pid,
          "started_at" => Time.now.iso8601
        }
        File.open(lock_path, File::WRONLY | File::CREAT | File::EXCL) { |file| file.write(JSON.generate(lock)) }
        { "status" => "locked", "request_id" => request_id }
      rescue Errno::EEXIST
        { "status" => "already_running" }
      end

      def mark_stale_lock
        status = write_status(
          "failed_stale_lock",
          "last_error" => "Refresh lock is stale."
        )
        release_lock
        status
      end

      def release_lock
        FileUtils.rm_f(lock_path)
      end

      def process_alive?(pid)
        return false unless pid

        Process.kill(0, Integer(pid))
        true
      rescue Errno::ESRCH, ArgumentError, TypeError
        false
      rescue Errno::EPERM
        true
      end

      def run_step(command)
        name = command.fetch("name")
        write_status("running", "current_step" => name, "command_results" => @step_results)
        started_at = Time.now
        stdout = +""
        stderr = +""
        status = nil

        Timeout.timeout(@timeout_seconds) do
          stdout, stderr, status = Open3.capture3(
            request_environment,
            *expanded_argv(command.fetch("argv")),
            chdir: @root
          )
        end

        result = {
          "name" => name,
          "exit_status" => status.exitstatus,
          "started_at" => started_at.iso8601,
          "finished_at" => Time.now.iso8601,
          "stdout_tail" => tail(redact(stdout)),
          "stderr_tail" => tail(redact(stderr))
        }
        @step_results << result
        capture_store_summary(name, stdout)

        raise "Step #{name} failed with exit status #{status.exitstatus}" unless status.success?
      rescue Timeout::Error
        @step_results << {
          "name" => name,
          "exit_status" => nil,
          "started_at" => started_at.iso8601,
          "finished_at" => Time.now.iso8601,
          "stderr_tail" => "Timed out after #{@timeout_seconds} seconds."
        }
        raise "Step #{name} timed out"
      end

      def validate_step(name)
        case name
        when /fetch|adapter/
          parse_json_file(relative_path("data/adapter-output/rss-fetch-latest.json"))
        when /ingest|canonical/
          canonical = parse_json_file(relative_path("data/canonical-items/latest.json"))
          @current_run_id = canonical["run_id"]
        when /store/
          validate_store_run
        when /signal|build/
          signals = parsed_temp_signals
          if @current_run_id && signals["input_run_id"] != @current_run_id
            raise "Signal input_run_id does not match canonical run_id"
          end
        end
      end

      def validate_store_run
        return unless @current_run_id

        found = Dir[relative_path("data/store/runs/*.jsonl")].any? do |path|
          File.readlines(path).any? { |line| line.include?(@current_run_id) }
        end
        raise "Store run record was not appended" unless found
      end

      def publish_signals
        previous_ids = latest_signal_ids
        current_ids = signal_ids(parsed_temp_signals)
        @signal_diff = {
          "changed" => previous_ids != current_ids,
          "previous_count" => previous_ids.length,
          "current_count" => current_ids.length,
          "added_ids" => current_ids - previous_ids,
          "removed_ids" => previous_ids - current_ids
        }
        FileUtils.mkdir_p(File.dirname(latest_signals_path))
        tmp_publish_path = "#{latest_signals_path}.#{@request_id}.tmp"
        FileUtils.cp(temp_signals_path, tmp_publish_path)
        FileUtils.mv(tmp_publish_path, latest_signals_path)
      end

      def parsed_temp_signals
        parse_json_file(temp_signals_path)
      end

      def write_status(status, extra = {})
        payload = {
          "status" => status,
          "started_at" => @run_started_at&.iso8601 || extra["started_at"],
          "finished_at" => status == "running" ? nil : Time.now.iso8601,
          "duration_seconds" => status == "running" || !@run_started_at ? nil : (Time.now - @run_started_at).round(3),
          "current_step" => extra["current_step"],
          "last_error" => extra["last_error"],
          "command_results" => extra["command_results"] || [],
          "store_summary" => @store_summary,
          "signal_diff" => @signal_diff,
          "last_successful_generated_at" => extra["last_successful_generated_at"],
          "last_successful_input_run_id" => extra["last_successful_input_run_id"]
        }
        FileUtils.mkdir_p(app_dir)
        File.write(status_path, "#{JSON.pretty_generate(payload)}\n")
        payload
      end

      def parse_json_file(path)
        JSON.parse(File.read(path))
      rescue Errno::ENOENT
        raise "Expected JSON artifact missing: #{path}"
      rescue JSON::ParserError => error
        raise "Expected JSON artifact is corrupt: #{path}: #{error.message}"
      end

      def request_environment
        { "REQUEST_ID" => @request_id.to_s }
      end

      def expanded_argv(argv)
        argv.map { |value| value.to_s.gsub("$REQUEST_ID", @request_id.to_s) }
      end

      def redact(value)
        value.to_s.gsub(SENSITIVE_PATTERN, "\\1\\2[REDACTED]")
      end

      def tail(value)
        value.to_s.lines.last(20).join
      end

      def capture_store_summary(name, stdout)
        return unless name == "store_canonical_jsonl" || name == "store"

        parsed = JSON.parse(stdout)
        @store_summary = parsed.slice("input_items", "appended_items", "skipped_duplicates", "dropped_items")
      rescue JSON::ParserError
        @store_summary = nil
      end

      def signal_ids(payload)
        Array(payload["signals"]).map { |signal| signal["id"].to_s }
      end

      def latest_signal_ids
        signal_ids(parse_json_file(latest_signals_path))
      rescue RuntimeError
        []
      end

      def cleanup_temp_dirs(keep: 5)
        dirs = Dir[relative_path("data/app/tmp/*")].select { |path| File.directory?(path) }
        dirs.each { |path| FileUtils.rm_rf(path) if File.basename(path) == "$REQUEST_ID" }

        refresh_dirs = dirs.reject { |path| File.basename(path) == "$REQUEST_ID" }
                           .sort_by { |path| File.mtime(path) }
        refresh_dirs.first([refresh_dirs.length - keep, 0].max).each { |path| FileUtils.rm_rf(path) }
      end

      def app_dir
        relative_path("data/app")
      end

      def status_path
        relative_path("data/app/refresh-status.json")
      end

      def lock_path
        relative_path("data/app/refresh.lock")
      end

      def latest_signals_path
        relative_path("data/signals/latest.json")
      end

      def temp_dir
        relative_path("data/app/tmp/#{@request_id}")
      end

      def temp_signals_path
        relative_path(temp_signals_relative_path)
      end

      def temp_signals_relative_path
        "data/app/tmp/#{@request_id || '$REQUEST_ID'}/signals.json"
      end

      def temp_markdown_relative_path
        "data/app/tmp/#{@request_id || '$REQUEST_ID'}/dashboard.md"
      end

      def temp_html_relative_path
        "data/app/tmp/#{@request_id || '$REQUEST_ID'}/generated-latest.html"
      end

      def relative_path(path)
        File.join(@root, path)
      end
    end
  end
end
