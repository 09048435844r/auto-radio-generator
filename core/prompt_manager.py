"""プロンプト管理モジュール

config/prompts.yaml からプロンプトを読み込み、提供するシングルトンクラス。
"""
from pathlib import Path
from typing import Any, Dict
import yaml


class PromptManager:
    """プロンプトを一元管理するクラス（シングルトン）"""
    
    _instance = None
    _prompts: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_prompts()
        return cls._instance
    
    def _load_prompts(self) -> None:
        """config/prompts.yaml を読み込む"""
        prompts_path = Path(__file__).parent.parent / "config" / "prompts.yaml"
        
        if not prompts_path.exists():
            raise FileNotFoundError(f"プロンプト設定ファイルが見つかりません: {prompts_path}")
        
        with open(prompts_path, "r", encoding="utf-8") as f:
            self._prompts = yaml.safe_load(f)
    
    def get_research_prompt(self, mode: str) -> str:
        """リサーチプロンプトを取得
        
        Args:
            mode: リサーチモード (debate/voices/trivia/weekly_digest/lecture)
        
        Returns:
            str: プロンプト文字列
        """
        if mode == "weekly_digest":
            return self._prompts["research"]["weekly_digest"]
        
        # 基本プロンプト + モード別追加指示
        base = self._prompts["research"]["base"]
        mode_specific = self._prompts["research"]["mode_specific"].get(mode, 
                        self._prompts["research"]["mode_specific"]["trivia"])
        return base + mode_specific
    
    def get_script_prompt(self, prompt_type: str, **kwargs) -> str:
        """台本生成プロンプトを取得
        
        Args:
            prompt_type: プロンプトタイプ (standard/weekly_digest/lecture/research_plan)
            **kwargs: プロンプト内の変数を展開するためのキーワード引数
        
        Returns:
            str: プロンプト文字列（変数展開済み）
        """
        prompt_template = self._prompts["script"].get(prompt_type, "")
        
        if not prompt_template:
            raise ValueError(f"プロンプトタイプが見つかりません: {prompt_type}")
        
        # 変数展開
        try:
            return prompt_template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"プロンプトの変数展開に失敗しました。不足している変数: {e}")
    
    def get_prompt(self, section: str, key: str = "default") -> str:
        """汎用プロンプト取得メソッド
        
        Args:
            section: プロンプトセクション名 (例: packaging, research, script)
            key: プロンプトキー (デフォルト: "default")
        
        Returns:
            str: プロンプトテキスト
        """
        if section not in self._prompts:
            raise ValueError(f"プロンプトセクションが見つかりません: {section}")
        
        section_data = self._prompts[section]
        
        # セクションが辞書の場合、keyで取得
        if isinstance(section_data, dict):
            prompt = section_data.get(key, "")
            if not prompt:
                raise ValueError(f"プロンプトが見つかりません: {section}.{key}")
            return prompt
        # セクションが文字列の場合、そのまま返す
        elif isinstance(section_data, str):
            return section_data
        else:
            raise ValueError(f"プロンプトの形式が不正です: {section}")
    
    def get_component(self, name: str) -> str:
        """再利用可能なコンポーネントを取得
        
        Args:
            name: コンポーネント名 (例: metadata_rules)
        
        Returns:
            str: コンポーネントのテキスト
        """
        if "components" not in self._prompts:
            raise ValueError("プロンプト設定ファイルに components セクションがありません")
        
        component = self._prompts["components"].get(name, "")
        
        if not component:
            raise ValueError(f"コンポーネントが見つかりません: {name}")
        
        return component
    
    def reload(self) -> None:
        """プロンプトを再読み込み（開発・デバッグ用）"""
        self._load_prompts()
