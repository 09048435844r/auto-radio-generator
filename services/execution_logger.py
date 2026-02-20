"""実行ログ・コスト履歴の記録サービス

月次ローテーション付きのJSONL形式でログを追記保存する。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import asdict

from core.models.execution_log import ExecutionLogEntry
from core.models.cost_log import CostLogEntry


class ExecutionLogger:
    """実行ログとコスト履歴をJSONL形式で記録するサービス"""
    
    def __init__(self, logs_dir: Optional[Path] = None):
        """
        Args:
            logs_dir: ログディレクトリのパス（デフォルト: プロジェクトルート/logs）
        """
        if logs_dir is None:
            # プロジェクトルートを推定
            project_root = Path(__file__).parent.parent
            logs_dir = project_root / "logs"
        
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_monthly_filename(self, base_name: str) -> str:
        """月次ローテーション用のファイル名を生成
        
        Args:
            base_name: ベースファイル名 (e.g., "execution_record", "cost_history")
        
        Returns:
            月次サフィックス付きファイル名 (e.g., "execution_record_2026-02.jsonl")
        """
        year_month = datetime.now().strftime("%Y-%m")
        return f"{base_name}_{year_month}.jsonl"
    
    def append_execution_log(self, entry: ExecutionLogEntry) -> None:
        """実行ログをJSONLファイルに追記
        
        Args:
            entry: 実行ログエントリ
        """
        filename = self._get_monthly_filename("execution_record")
        log_path = self.logs_dir / filename
        
        try:
            # Pydanticモデルを辞書に変換してJSON化
            entry_dict = entry.model_dump()
            json_line = json.dumps(entry_dict, ensure_ascii=False)
            
            # アトミックな追記（append mode）
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")
        
        except Exception as e:
            # ログ書き込みエラーはワークフローを止めない
            print(f"[WARN] Failed to write execution log: {e}")
    
    def append_cost_log(self, entry: CostLogEntry) -> None:
        """コスト履歴をJSONLファイルに追記
        
        Args:
            entry: コストログエントリ
        """
        filename = self._get_monthly_filename("cost_history")
        log_path = self.logs_dir / filename
        
        try:
            # Pydanticモデルを辞書に変換してJSON化
            entry_dict = entry.model_dump()
            json_line = json.dumps(entry_dict, ensure_ascii=False)
            
            # アトミックな追記（append mode）
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")
        
        except Exception as e:
            # ログ書き込みエラーはワークフローを止めない
            print(f"[WARN] Failed to write cost log: {e}")
    
    def read_execution_logs(self, year_month: Optional[str] = None) -> list[ExecutionLogEntry]:
        """実行ログを読み込む（デバッグ・分析用）
        
        Args:
            year_month: 読み込む年月 (e.g., "2026-02")。Noneの場合は当月。
        
        Returns:
            実行ログエントリのリスト
        """
        if year_month is None:
            year_month = datetime.now().strftime("%Y-%m")
        
        filename = f"execution_record_{year_month}.jsonl"
        log_path = self.logs_dir / filename
        
        if not log_path.exists():
            return []
        
        entries = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry_dict = json.loads(line)
                    entries.append(ExecutionLogEntry(**entry_dict))
        
        return entries
    
    def read_cost_logs(self, year_month: Optional[str] = None) -> list[CostLogEntry]:
        """コスト履歴を読み込む（デバッグ・分析用）
        
        Args:
            year_month: 読み込む年月 (e.g., "2026-02")。Noneの場合は当月。
        
        Returns:
            コストログエントリのリスト
        """
        if year_month is None:
            year_month = datetime.now().strftime("%Y-%m")
        
        filename = f"cost_history_{year_month}.jsonl"
        log_path = self.logs_dir / filename
        
        if not log_path.exists():
            return []
        
        entries = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry_dict = json.loads(line)
                    entries.append(CostLogEntry(**entry_dict))
        
        return entries
