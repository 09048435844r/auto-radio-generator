from core.models.config import load_config
from openai import OpenAI
from datetime import datetime, timezone


def main():
    config = load_config()
    api_key = config.env.perplexity_api_key

    print(f"[UTC] {datetime.now(timezone.utc).isoformat()}")
    print(f"key_prefix={api_key[:5] if api_key else 'None'}")
    print(f"key_len={len(api_key) if api_key else 0}")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.perplexity.ai",
    )

    response = client.chat.completions.create(
        model="sonar",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=10,
    )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
