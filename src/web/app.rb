# frozen_string_literal: true

require "json"
require "uri"

require_relative "data_repository"
require_relative "pipeline_runner"

module FounderIntelligence
  module Web
    Response = Struct.new(:status, :headers, :body, keyword_init: true)

    class App
      DISALLOWED_REFRESH_KEYS = %w[command script path argv args].freeze
      DEFAULT_ALLOWED_ORIGINS = ["http://127.0.0.1:4567", "http://localhost:4567"].freeze

      def initialize(root:, runner: nil, public_dir: nil, allowed_origins: nil)
        @root = File.expand_path(root)
        @repository = DataRepository.new(root: @root)
        @runner = runner || PipelineRunner.new(root: @root)
        @public_dir = public_dir || File.expand_path("public", __dir__)
        @allowed_origins = Array(allowed_origins || DEFAULT_ALLOWED_ORIGINS).map { |value| normalize_origin(value) }.compact
      end

      def handle(method, path, headers, body)
        method = method.to_s.upcase
        route_path = path.to_s.split("?").first

        case [method, route_path]
        when ["GET", "/"]
          html_response(read_public_file("index.html"))
        when ["GET", "/app.js"]
          asset_response("app.js", "application/javascript; charset=utf-8")
        when ["GET", "/styles.css"]
          asset_response("styles.css", "text/css; charset=utf-8")
        when ["GET", "/api/signals/latest"]
          json_response(@repository.latest_signals)
        when ["GET", "/api/runs/latest"]
          json_response(@repository.latest_run)
        when ["GET", "/api/refresh/status"]
          json_response(@repository.refresh_status)
        when ["GET", "/api/profile"]
          json_response(@repository.profile)
        when ["PUT", "/api/profile"]
          handle_profile_update(headers, body)
        when ["GET", "/api/sources"]
          json_response(@repository.sources)
        when ["PUT", "/api/sources"]
          handle_sources_update(headers, body)
        when ["GET", "/api/health"]
          json_response("status" => "ok")
        when ["POST", "/api/refresh"]
          handle_refresh(headers, body)
        else
          return handle_source_update(route_path, headers, body) if method == "POST" && route_path.start_with?("/api/sources/")
          return handle_source_update(route_path, headers, body) if method == "PATCH" && route_path.start_with?("/api/sources/")
          return public_asset_response(route_path) if route_path.start_with?("/assets/")

          json_response({ "status" => "not_found" }, status: 404)
        end
      end

      private

      def handle_refresh(headers, body)
        return json_response({ "status" => "forbidden" }, status: 403) unless same_origin?(headers)

        payload = parse_body(body)
        return json_response({ "status" => "bad_request", "message" => "Invalid JSON body." }, status: 400) unless payload
        if (payload.keys.map(&:to_s) & DISALLOWED_REFRESH_KEYS).any?
          return json_response({ "status" => "bad_request", "message" => "Refresh does not accept command parameters." }, status: 400)
        end

        result = @runner.refresh
        response_status = result["status"] == "already_running" ? 409 : 200
        json_response(result, status: response_status)
      end

      def handle_profile_update(headers, body)
        return json_response({ "status" => "forbidden" }, status: 403) unless same_origin?(headers)

        payload = parse_body(body)
        return json_response({ "status" => "bad_request", "message" => "Invalid JSON body." }, status: 400) unless payload

        result = @repository.update_profile(payload["content"])
        json_response(result, status: result["status"] == "saved" ? 200 : 400)
      end

      def handle_source_update(route_path, headers, body)
        return json_response({ "status" => "forbidden" }, status: 403) unless same_origin?(headers)

        source_id = route_path.delete_prefix("/api/sources/")
        return json_response({ "status" => "not_found" }, status: 404) if source_id.empty? || source_id.include?("/")

        payload = parse_body(body)
        return json_response({ "status" => "bad_request", "message" => "Invalid JSON body." }, status: 400) unless payload

        result = @repository.update_source_enabled(source_id, payload["enabled"])
        status = case result["status"]
                 when "saved" then 200
                 when "not_found" then 404
                 else 400
                 end
        json_response(result, status: status)
      end

      def handle_sources_update(headers, body)
        return json_response({ "status" => "forbidden" }, status: 403) unless same_origin?(headers)

        payload = parse_body(body)
        return json_response({ "status" => "bad_request", "message" => "Invalid JSON body." }, status: 400) unless payload

        result = @repository.update_sources(payload["content"])
        json_response(result, status: result["status"] == "saved" ? 200 : 400)
      end

      def parse_body(body)
        return {} if body.nil? || body.to_s.strip.empty?

        parsed = JSON.parse(body)
        parsed.is_a?(Hash) ? parsed : nil
      rescue JSON::ParserError
        nil
      end

      def same_origin?(headers)
        origin = header(headers, "origin")
        return true unless origin

        normalized = normalize_origin(origin)
        normalized && @allowed_origins.include?(normalized)
      end

      def normalize_origin(value)
        uri = URI.parse(value.to_s)
        return nil unless uri.scheme == "http" && uri.host

        port = uri.port && uri.port != uri.default_port ? ":#{uri.port}" : ""
        "#{uri.scheme}://#{uri.host}#{port}"
      rescue URI::InvalidURIError
        false
      end

      def header(headers, key)
        headers.find { |name, _| name.to_s.downcase == key }&.last
      end

      def read_public_file(name)
        File.read(File.join(@public_dir, name))
      end

      def html_response(body)
        Response.new(
          status: 200,
          headers: { "content-type" => "text/html; charset=utf-8" },
          body: body
        )
      end

      def asset_response(name, content_type)
        Response.new(
          status: 200,
          headers: { "content-type" => content_type },
          body: read_public_file(name)
        )
      rescue Errno::ENOENT
        json_response({ "status" => "not_found" }, status: 404)
      end

      def public_asset_response(route_path)
        relative_path = route_path.delete_prefix("/")
        full_path = File.expand_path(relative_path, @public_dir)
        assets_root = File.expand_path("assets", @public_dir)
        return json_response({ "status" => "not_found" }, status: 404) unless full_path.start_with?("#{assets_root}/")
        return json_response({ "status" => "not_found" }, status: 404) unless File.file?(full_path)

        Response.new(
          status: 200,
          headers: { "content-type" => content_type_for(full_path) },
          body: File.binread(full_path)
        )
      end

      def content_type_for(path)
        case File.extname(path)
        when ".svg"
          "image/svg+xml"
        when ".ico"
          "image/x-icon"
        else
          "application/octet-stream"
        end
      end

      def json_response(payload, status: 200)
        Response.new(
          status: status,
          headers: { "content-type" => "application/json; charset=utf-8" },
          body: "#{JSON.pretty_generate(payload)}\n"
        )
      end
    end
  end
end
