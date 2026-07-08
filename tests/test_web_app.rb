# frozen_string_literal: true

require "fileutils"
require "json"
require "minitest/autorun"
require "tmpdir"

ROOT = File.expand_path("..", __dir__)
$LOAD_PATH.unshift(ROOT)

require "src/web/app"

class WebAppTest < Minitest::Test
  ORIGIN = "http://127.0.0.1:4567"

  def setup
    @dir = Dir.mktmpdir("fi-web-app")
    write("config/user-profile.yml", sample_profile_yaml)
    write("config/sources.yml", sample_sources_yaml)
    write_json("data/signals/latest.json", sample_signal_output)
    calls = [0]
    @refresh_calls = calls
    runner = Object.new
    runner.define_singleton_method(:refresh) do
      calls[0] += 1
      { "status" => "started" }
    end
    @app = FounderIntelligence::Web::App.new(root: @dir, runner: runner)
  end

  def teardown
    FileUtils.remove_entry(@dir)
  end

  def test_homepage_is_web_app_shell_not_dashboard_template_or_sample_data
    response = @app.handle("GET", "/", {}, nil)

    assert_equal 200, response.status
    assert_includes response.body, "command-bar"
    assert_includes response.body, "source-folders"
    assert_includes response.body, "reset-source-library"
    assert_includes response.body, "source-config-text"
    assert_includes response.body, "user-profile-file"
    assert_includes response.body, "user-profile.yml"
    refute_includes response.body, "user.md"
    refute_includes response.body, "assets/sample-data.js"
    assert_includes response.body, "app.js"
  end

  def test_app_javascript_uses_api_data_not_sample_globals
    response = @app.handle("GET", "/app.js", {}, nil)

    assert_equal 200, response.status
    assert_includes response.body, 'fetchJson("/api/signals/latest")'
    assert_includes response.body, "folder-preview-grid"
    assert_includes response.body, "config/sources.yml"
    assert_includes response.body, 'fetchJson("/api/sources")'
    assert_includes response.body, 'fetchJson("/api/sources", {'
    assert_includes response.body, 'fetchJson("/api/profile")'
    assert_includes response.body, "data-source-toggle"
    assert_includes response.body, "renderError"
    refute_includes response.body, "data-source-delete"
    refute_includes response.body, "USER_MD"
    refute_includes response.body, "window.FI_ITEMS"
    refute_includes response.body, "window.FI_CLUSTERS"
    refute_includes response.body, "window.FI_METRICS"
  end

  def test_brand_logo_assets_are_served_from_web_public_directory
    response = @app.handle("GET", "/assets/brand-logos/github.svg", {}, nil)

    assert_equal 200, response.status
    assert_equal "image/svg+xml", response.headers.fetch("content-type")
  end

  def test_latest_signals_api_returns_successful_signal_output
    response = @app.handle("GET", "/api/signals/latest", {}, nil)

    assert_equal 200, response.status
    payload = JSON.parse(response.body)
    assert_equal "run-api", payload.fetch("input_run_id")
  end

  def test_profile_api_reads_and_writes_user_profile_yml
    get_response = @app.handle("GET", "/api/profile", {}, nil)
    assert_equal 200, get_response.status
    get_payload = JSON.parse(get_response.body)
    assert_equal "config/user-profile.yml", get_payload.fetch("path")
    assert_includes get_payload.fetch("content"), "Founder Intelligence User"

    updated = sample_profile_yaml.sub("Founder Intelligence User", "Updated User")
    put_response = @app.handle("PUT", "/api/profile", { "origin" => ORIGIN }, JSON.generate("content" => updated))

    assert_equal 200, put_response.status
    assert_includes File.read(File.join(@dir, "config/user-profile.yml")), "Updated User"
  end

  def test_profile_api_rejects_invalid_yaml
    before = File.read(File.join(@dir, "config/user-profile.yml"))

    response = @app.handle("PUT", "/api/profile", { "origin" => ORIGIN }, JSON.generate("content" => "version: ["))

    assert_equal 400, response.status
    assert_equal before, File.read(File.join(@dir, "config/user-profile.yml"))
  end

  def test_profile_api_rejects_semantically_invalid_profile
    before = File.read(File.join(@dir, "config/user-profile.yml"))
    invalid = "version: 1\nuser:\n  name: \ninterests: []\n"

    response = @app.handle("PUT", "/api/profile", { "origin" => ORIGIN }, JSON.generate("content" => invalid))

    assert_equal 400, response.status
    assert_equal before, File.read(File.join(@dir, "config/user-profile.yml"))
  end

  def test_sources_api_reads_real_config_and_updates_enabled
    get_response = @app.handle("GET", "/api/sources", {}, nil)
    assert_equal 200, get_response.status
    payload = JSON.parse(get_response.body)
    github = payload.fetch("sources").find { |source| source.fetch("id") == "github-trending-daily" }
    assert_equal true, github.fetch("enabled")
    assert_equal true, github.fetch("runnable")

    patch_response = @app.handle(
      "POST",
      "/api/sources/github-trending-daily",
      { "origin" => ORIGIN },
      JSON.generate("enabled" => false)
    )

    assert_equal 200, patch_response.status
    assert_includes File.read(File.join(@dir, "config/sources.yml")), "enabled: false"
  end

  def test_sources_api_writes_full_sources_yml
    updated = sample_sources_yaml.sub("GitHub Trending Daily", "GitHub Trending Edited")

    put_response = @app.handle(
      "PUT",
      "/api/sources",
      { "origin" => ORIGIN },
      JSON.generate("content" => updated)
    )

    assert_equal 200, put_response.status
    assert_includes File.read(File.join(@dir, "config/sources.yml")), "GitHub Trending Edited"
    payload = JSON.parse(put_response.body)
    assert_equal "config/sources.yml", payload.fetch("path")
  end

  def test_sources_api_rejects_invalid_sources_yml
    before = File.read(File.join(@dir, "config/sources.yml"))

    response = @app.handle(
      "PUT",
      "/api/sources",
      { "origin" => ORIGIN },
      JSON.generate("content" => "version: 1\nsources:\n  - name: Missing id\n")
    )

    assert_equal 400, response.status
    assert_equal before, File.read(File.join(@dir, "config/sources.yml"))
  end

  def test_sources_api_rejects_semantically_invalid_rss_source
    before = File.read(File.join(@dir, "config/sources.yml"))
    invalid = <<~YAML
      version: 1
      sources:
        - id: broken-rss
          name: Broken RSS
          source_type: rss
          provider: github
          enabled: true
          category: developer_trends
          connection: {}
    YAML

    response = @app.handle(
      "PUT",
      "/api/sources",
      { "origin" => ORIGIN },
      JSON.generate("content" => invalid)
    )

    assert_equal 400, response.status
    assert_equal before, File.read(File.join(@dir, "config/sources.yml"))
  end

  def test_sources_api_rejects_enabled_non_rss_source
    before = File.read(File.join(@dir, "config/sources.yml"))
    invalid = <<~YAML
      version: 1
      sources:
        - id: unsupported-mcp
          name: Unsupported MCP
          source_type: mcp
          provider: wechat
          enabled: true
          category: founder_research
          connection:
            tool: wechat-mcp
    YAML

    response = @app.handle(
      "PUT",
      "/api/sources",
      { "origin" => ORIGIN },
      JSON.generate("content" => invalid)
    )

    assert_equal 400, response.status
    assert_equal before, File.read(File.join(@dir, "config/sources.yml"))
  end

  def test_sources_api_rejects_unknown_source
    response = @app.handle(
      "POST",
      "/api/sources/missing-source",
      { "origin" => ORIGIN },
      JSON.generate("enabled" => false)
    )

    assert_equal 404, response.status
  end

  def test_sources_api_keeps_patch_compatibility_inside_app
    response = @app.handle(
      "PATCH",
      "/api/sources/github-trending-daily",
      { "origin" => ORIGIN },
      JSON.generate("enabled" => false)
    )

    assert_equal 200, response.status
  end

  def test_refresh_rejects_cross_origin_request
    response = @app.handle("POST", "/api/refresh", { "origin" => "http://evil.example" }, "{}")

    assert_equal 403, response.status
    assert_equal 0, @refresh_calls[0]
  end

  def test_refresh_rejects_origin_that_only_has_localhost_prefix
    response = @app.handle("POST", "/api/refresh", { "origin" => "http://127.0.0.1.evil.example" }, "{}")

    assert_equal 403, response.status
    assert_equal 0, @refresh_calls[0]
  end

  def test_refresh_rejects_same_host_wrong_port
    response = @app.handle("POST", "/api/refresh", { "origin" => "http://127.0.0.1:9999" }, "{}")

    assert_equal 403, response.status
    assert_equal 0, @refresh_calls[0]
  end

  def test_refresh_rejects_command_parameters
    response = @app.handle("POST", "/api/refresh", { "origin" => ORIGIN }, JSON.generate("command" => "whoami"))

    assert_equal 400, response.status
    assert_equal 0, @refresh_calls[0]
  end

  def test_refresh_accepts_same_origin_without_parameters
    response = @app.handle("POST", "/api/refresh", { "origin" => ORIGIN }, "{}")

    assert_equal 200, response.status
    payload = JSON.parse(response.body)
    assert_equal "started", payload.fetch("status")
    assert_equal 1, @refresh_calls[0]
  end

  private

  def write_json(path, value)
    full_path = File.join(@dir, path)
    FileUtils.mkdir_p(File.dirname(full_path))
    File.write(full_path, "#{JSON.pretty_generate(value)}\n")
  end

  def write(path, content)
    full_path = File.join(@dir, path)
    FileUtils.mkdir_p(File.dirname(full_path))
    File.write(full_path, content)
  end

  def sample_profile_yaml
    <<~YAML
      version: 1
      user:
        name: Founder Intelligence User
      interests:
        - AI coding
      output_preferences:
        default_top_n: 10
    YAML
  end

  def sample_sources_yaml
    <<~YAML
      version: 1
      sources:
        - id: github-trending-daily
          name: GitHub Trending Daily
          source_type: rss
          provider: github
          fetcher: rsshub
          enabled: true
          priority: high
          category: developer_trends
          connection:
            rss_url: http://localhost:1200/github/trending/daily/any
          schedule:
            refresh_interval_minutes: 30
          tags:
            - open-source
        - id: disabled-source
          name: Disabled Source
          source_type: rss
          provider: example
          fetcher: rsshub
          enabled: false
          category: reference_feed
          connection:
            rss_url: http://localhost:1200/example
      source_templates:
        future_mcp:
          source_type: mcp
          provider: future
          enabled: false
          category: future
    YAML
  end

  def sample_signal_output
    {
      "contract_version" => 1,
      "generated_at" => "2026-07-08T10:00:00+08:00",
      "input_run_id" => "run-api",
      "summary" => { "input_items" => 2, "signals" => 1, "top_n" => 10 },
      "signals" => [
        {
          "id" => "signal-api",
          "title" => "API Signal",
          "source" => { "name" => "GitHub Trending", "provider" => "github", "type" => "rss" },
          "what_happened" => "Signal rendered from API.",
          "why_important" => "Important.",
          "why_relevant" => "Relevant.",
          "recommended_questions" => ["Question?"],
          "risks" => ["Risk."],
          "total_score" => 4.5,
          "importance_score" => 5,
          "relevance_score" => 4,
          "tags" => ["rss"]
        }
      ]
    }
  end
end
