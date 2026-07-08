#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"
require "webrick"

require_relative "web/app"

options = {
  "host" => "127.0.0.1",
  "port" => 4567,
  "root" => File.expand_path("..", __dir__)
}

OptionParser.new do |opts|
  opts.banner = "Usage: ruby src/web_app.rb [options]"
  opts.on("--host HOST", "Bind host, defaults to 127.0.0.1") { |value| options["host"] = value }
  opts.on("--port PORT", Integer, "Port, defaults to 4567") { |value| options["port"] = value }
  opts.on("--root PATH", "Project root") { |value| options["root"] = File.expand_path(value) }
end.parse!(ARGV)

allowed_hosts = [options.fetch("host")]
allowed_hosts += ["127.0.0.1", "localhost"] if ["127.0.0.1", "localhost"].include?(options.fetch("host"))
allowed_origins = allowed_hosts.uniq.map { |host| "http://#{host}:#{options.fetch("port")}" }

app = FounderIntelligence::Web::App.new(root: options.fetch("root"), allowed_origins: allowed_origins)
server = WEBrick::HTTPServer.new(
  BindAddress: options.fetch("host"),
  Port: options.fetch("port"),
  AccessLog: [],
  Logger: WEBrick::Log.new($stderr, WEBrick::Log::INFO)
)

server.mount_proc("/") do |request, response|
  app_response = app.handle(request.request_method, request.path, request.header.transform_values(&:first), request.body)
  response.status = app_response.status
  app_response.headers.each { |key, value| response[key] = value }
  response.body = app_response.body
end

trap("INT") { server.shutdown }
trap("TERM") { server.shutdown }

server.start
