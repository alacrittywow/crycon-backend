#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from crycon.config import load_settings
from supabase import create_client


def main() -> None:
    settings = load_settings()
    url = settings.require("SUPABASE_URL")
    key = settings.require("SUPABASE_KEY")

    print("=" * 72)
    print("Testing Supabase connection")
    print("=" * 72)
    print(f"SUPABASE_URL present: {bool(url)}")
    print(f"SUPABASE_KEY present: {bool(key)}")
    print("=" * 72)

    client = create_client(url, key)

    payload = {
        "job_type": "connection_test",
        "query": "hello from new pycharm project",
        "status": "done",
        "result_count": 1,
    }

    insert_response = (
        client
        .table("parser_jobs")
        .insert(payload)
        .execute()
    )

    print("Insert response:")
    print(insert_response.data)

    select_response = (
        client
        .table("parser_jobs")
        .select("*")
        .eq("job_type", "connection_test")
        .limit(5)
        .execute()
    )

    print("Select response:")
    print(select_response.data)

    print("=" * 72)
    print("Supabase connection OK")
    print("=" * 72)


if __name__ == "__main__":
    main()
