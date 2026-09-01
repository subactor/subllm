# Preprompt

Treat a valid provider cooldown as a bounded circuit breaker. Never persist or
emit prompts, responses, credentials, headers or raw provider errors. Preserve
policy order among eligible routes and recover automatically after expiry.
