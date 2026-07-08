# frozen_string_literal: true

require "fileutils"
require "json"
require "minitest/autorun"
require "rbconfig"
require "time"
require "tmpdir"

ROOT = File.expand_path("..", __dir__)
$LOAD_PATH.unshift(ROOT)

require "src/web/data_repository"
require "src/web/pipeline_runner"

class WebDataRepositoryTest < Minitest::Test
  def setup
    @dir = Dir.mktmpdir("fi-web-repo")
    @repo = FounderIntelligence::Web::DataRepository.new(root: @dir)
  end

  def teardown
    FileUtils.remove_entry(@dir)
  end

  def test_latest_signals_returns_empty_when_no_successful_file_exists
    response = @repo.latest_signals

    assert_equal "empty", response.fetch("status")
    assert_equal "No successful signals have been generated yet.", response.fetch("message")
  end

  def test_latest_signals_rejects_corrupt_json_as_error_not_empty
    write("data/signals/latest.json", "{not-json")

    response = @repo.latest_signals

    assert_equal "error", response.fetch("status")
    assert_match(/signal file/i, response.fetch("message"))
  end

  def test_latest_signals_returns_valid_successful_signal_output
    write_json("data/signals/latest.json", sample_signal_output("run-1"))

    response = @repo.latest_signals

    assert_equal "run-1", response.fetch("input_run_id")
    assert_equal 1, response.fetch("signals").length
  end

  private

  def write(path, content)
    full_path = File.join(@dir, path)
    FileUtils.mkdir_p(File.dirname(full_path))
    File.write(full_path, content)
  end

  def write_json(path, value)
    write(path, "#{JSON.pretty_generate(value)}\n")
  end

  def sample_signal_output(run_id)
    {
      "contract_version" => 1,
      "generated_at" => "2026-07-08T10:00:00+08:00",
      "input_run_id" => run_id,
      "summary" => { "input_items" => 1, "signals" => 1, "top_n" => 10 },
      "signals" => [
        {
          "id" => "signal-1",
          "title" => "Signal 1",
          "source" => { "name" => "GitHub Trending", "provider" => "github", "type" => "rss" },
          "what_happened" => "A useful thing happened.",
          "total_score" => 4.2,
          "importance_score" => 4,
          "relevance_score" => 5,
          "tags" => ["rss"]
        }
      ]
    }
  end
end

class WebPipelineRunnerTest < Minitest::Test
  def setup
    @dir = Dir.mktmpdir("fi-web-runner")
  end

  def teardown
    FileUtils.remove_entry(@dir)
  end

  def test_successful_refresh_publishes_validated_temp_signals
    write_json("data/signals/latest.json", sample_signal_output("run-old"))
    runner = runner_with_commands([
      write_json_command("adapter", "data/adapter-output/rss-fetch-latest.json", { "status" => "ok" }),
      write_json_command("canonical", "data/canonical-items/latest.json", { "run_id" => "run-new", "items" => [] }),
      append_jsonl_command("store", "data/store/runs/2026-07-08.jsonl", { "input_run_id" => "run-new" }, stdout: { "input_items" => 1, "appended_items" => 1, "skipped_duplicates" => 0 }),
      write_json_command("signals", "data/app/tmp/$REQUEST_ID/signals.json", sample_signal_output("run-new"))
    ])

    status = runner.refresh

    assert_equal "succeeded", status.fetch("status")
    refute_nil status.fetch("started_at")
    assert_kind_of Numeric, status.fetch("duration_seconds")
    assert_equal({ "input_items" => 1, "appended_items" => 1, "skipped_duplicates" => 0 }, status.fetch("store_summary"))
    assert_equal false, status.fetch("signal_diff").fetch("changed")
    latest = read_json("data/signals/latest.json")
    assert_equal "run-new", latest.fetch("input_run_id")
    persisted_status = read_json("data/app/refresh-status.json")
    assert_equal "succeeded", persisted_status.fetch("status")
    refute_nil persisted_status.fetch("started_at")
  end

  def test_runner_expands_request_id_placeholder_in_command_arguments
    runner = runner_with_commands([
      write_json_command_without_manual_expansion("adapter", "data/adapter-output/rss-fetch-latest.json", { "status" => "ok" }),
      write_json_command_without_manual_expansion("canonical", "data/canonical-items/latest.json", { "run_id" => "run-new", "items" => [] }),
      append_jsonl_command("store", "data/store/runs/2026-07-08.jsonl", { "input_run_id" => "run-new" }),
      write_json_command_without_manual_expansion("signals", "data/app/tmp/$REQUEST_ID/signals.json", sample_signal_output("run-new"))
    ])

    status = runner.refresh

    assert_equal "succeeded", status.fetch("status")
    assert_equal "run-new", read_json("data/signals/latest.json").fetch("input_run_id")
  end

  def test_failed_refresh_does_not_overwrite_previous_successful_signals
    write_json("data/signals/latest.json", sample_signal_output("run-old"))
    before_hash = File.read(File.join(@dir, "data/signals/latest.json"))
    runner = runner_with_commands([
      write_json_command("adapter", "data/adapter-output/rss-fetch-latest.json", { "status" => "ok" }),
      failing_command("canonical")
    ])

    status = runner.refresh

    assert_equal "failed", status.fetch("status")
    assert_equal before_hash, File.read(File.join(@dir, "data/signals/latest.json"))
    assert_equal "run-old", read_json("data/signals/latest.json").fetch("input_run_id")
  end

  def test_refresh_is_rejected_when_lock_exists_for_running_process
    runner = runner_with_commands([])
    lock_path = File.join(@dir, "data/app/refresh.lock")
    FileUtils.mkdir_p(File.dirname(lock_path))
    File.write(lock_path, JSON.generate("request_id" => "held", "pid" => Process.pid, "started_at" => Time.now.iso8601))

    status = runner.refresh

    assert_equal "already_running", status.fetch("status")
  end

  private

  def runner_with_commands(commands)
    FounderIntelligence::Web::PipelineRunner.new(root: @dir, commands: commands, timeout_seconds: 5)
  end

  def write_json_command(name, path, value)
    {
      "name" => name,
      "argv" => [
        RbConfig.ruby,
        "-rjson",
        "-rfileutils",
        "-e",
        "path = ARGV.fetch(0).gsub('$REQUEST_ID', ENV.fetch('REQUEST_ID')); FileUtils.mkdir_p(File.dirname(path)); File.write(path, JSON.generate(JSON.parse(ARGV.fetch(1))))",
        path,
        JSON.generate(value)
      ]
    }
  end

  def write_json_command_without_manual_expansion(name, path, value)
    {
      "name" => name,
      "argv" => [
        RbConfig.ruby,
        "-rjson",
        "-rfileutils",
        "-e",
        "path = ARGV.fetch(0); FileUtils.mkdir_p(File.dirname(path)); File.write(path, JSON.generate(JSON.parse(ARGV.fetch(1))))",
        path,
        JSON.generate(value)
      ]
    }
  end

  def append_jsonl_command(name, path, value, stdout: nil)
    {
      "name" => name,
      "argv" => [
        RbConfig.ruby,
        "-rjson",
        "-rfileutils",
        "-e",
        "path = ARGV.fetch(0); FileUtils.mkdir_p(File.dirname(path)); File.open(path, 'a') { |file| file.puts(JSON.generate(JSON.parse(ARGV.fetch(1)))) }; puts(ARGV.fetch(2)) unless ARGV.fetch(2).empty?",
        path,
        JSON.generate(value),
        stdout ? JSON.pretty_generate(stdout) : ""
      ]
    }
  end

  def failing_command(name)
    { "name" => name, "argv" => [RbConfig.ruby, "-e", "exit 7"] }
  end

  def write_json(path, value)
    full_path = File.join(@dir, path)
    FileUtils.mkdir_p(File.dirname(full_path))
    File.write(full_path, "#{JSON.pretty_generate(value)}\n")
  end

  def read_json(path)
    JSON.parse(File.read(File.join(@dir, path)))
  end

  def sample_signal_output(run_id)
    {
      "contract_version" => 1,
      "generated_at" => "2026-07-08T10:00:00+08:00",
      "input_run_id" => run_id,
      "summary" => { "input_items" => 1, "signals" => 1, "top_n" => 10 },
      "signals" => [{ "id" => "signal-1", "title" => "Signal 1", "total_score" => 4.2 }]
    }
  end
end
