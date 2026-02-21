# -*- coding: utf-8 -*-
from datetime import datetime
from pathlib import Path

from app import (
    PROJECT_ROOT,
    get_asset_choices,
    save_settings_from_ui,
    generate_video,
    update_dashboard,
)


def main() -> None:
    assets = get_asset_choices()
    bg = assets.get("backgrounds", ["default.png"])
    bgm = assets.get("bgm", ["default.mp3"])

    background = bg[0] if bg else ""
    bgm_file = bgm[0] if bgm else None

    month = datetime.now().strftime("%Y-%m")
    exec_log_path = PROJECT_ROOT / "logs" / f"execution_record_{month}.jsonl"
    before_count = 0
    if exec_log_path.exists():
        before_count = sum(1 for _ in exec_log_path.open("r", encoding="utf-8"))

    # 1) SettingsタブでMockをONして保存、に相当する処理
    save_msg = save_settings_from_ui(
        research_mode="トリビア (雑学)",
        background_image=background,
        bgm_file=bgm_file,
        bgm_volume=0.15,
        fade_time=3.0,
        speed_scale=1.1,
        enable_spectrum=True,
        mock_mode=True,
        upload_enabled=False,
        footer_text="",
    )

    # 2) Generatorの実行、に相当する処理
    result = generate_video(
        theme="最終テスト: Mockモード確認",
        research_mode="トリビア (雑学)",
        background_image=background,
        bgm_file=bgm_file,
        bgm_volume=0.15,
        fade_time=3.0,
        speed_scale=1.1,
        enable_spectrum=True,
        use_mock=True,
        avoid_topics="",
        upload_to_youtube=False,
        footer_text="",
    )

    video_path, log_output, cost_output, title_output, desc_output, youtube_status = result

    after_count = 0
    if exec_log_path.exists():
        after_count = sum(1 for _ in exec_log_path.open("r", encoding="utf-8"))

    # 3) Dashboard反映確認
    (
        total_exec,
        total_cost,
        avg_cost,
        success_rate,
        table,
        cost_chart,
        usage_chart,
        dash_status,
    ) = update_dashboard(month)

    mock_log_hit = ("mock" in log_output.lower()) or ("テスト" in log_output)
    row_added = after_count == before_count + 1

    cost_trace_points = 0
    if hasattr(cost_chart, "data") and len(cost_chart.data) > 0:
        first_trace = cost_chart.data[0]
        y = getattr(first_trace, "y", None)
        if y is not None:
            cost_trace_points = len(y)

    def safe_text(value: object) -> str:
        return str(value).encode("cp932", errors="replace").decode("cp932", errors="replace")

    print("=== Mock Integration Final Test ===")
    print(f"Save message: {safe_text(save_msg)}")
    print(f"Before rows: {before_count}")
    print(f"After rows: {after_count}")
    print(f"Row added: {row_added}")
    print(f"Mock log hit: {mock_log_hit}")
    print(f"Dashboard total_exec: {total_exec}")
    print(f"Dashboard table rows: {len(table) if hasattr(table, '__len__') else 'N/A'}")
    print(f"Cost chart points: {cost_trace_points}")
    print(f"Dashboard status: {safe_text(dash_status)}")
    print("--- LOG SNIPPET START ---")
    print(safe_text(log_output[:1200]))
    print("--- LOG SNIPPET END ---")


if __name__ == "__main__":
    main()
