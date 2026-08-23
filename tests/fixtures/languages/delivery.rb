# frozen_string_literal: true

require "json"

# Outbound webhook delivery with bounded retries.
module Webhooks
  DEFAULT_BACKOFF = [1, 2, 5, 15].freeze

  class DeliveryError < StandardError; end

  # A single delivery attempt (see RFC 6455 section 5.2 for framing details).
  class Delivery
    attr_reader :url, :payload

    def initialize(url,
                   payload,
                   headers: {})
      @url = url
      @payload = payload
      @headers = headers
      @attempts = 0
    end

    # No parentheses at all -- idiomatic Ruby predicate.
    def retryable?
      @attempts < DEFAULT_BACKOFF.length
    end

    def self.from_json(raw)
      data = JSON.parse(raw)
      new(data["url"], data["payload"], headers: data.fetch("headers", {}))
    end

    def perform!
      raise DeliveryError, "too many attempts" unless retryable?

      body = { "event" => "ping", "note" => "def perform! { not a method }" }
      @attempts += 1
      if body.key?("event")
        while retryable?
          break unless dispatch(body)
        end
      end
      body
    end

    private

    def dispatch(body)
      # def legacy_dispatch(body) -- removed in v2.1, do not resurrect
      handler = ->(chunk) { chunk.to_s.bytesize }
      handler.call(body)
    end
  end
end
