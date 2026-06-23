# pyright: reportImplicitRelativeImport=false

from gateway.prompts import get_chat_system_prompt


class TestGetChatSystemPrompt:
    def test_default_no_user_text_no_reference(self):
        prompt = get_chat_system_prompt("en")
        assert "Feature Extractor Reference" not in prompt
        assert "## Feature Extractor Reference" not in prompt

    def test_default_no_user_text_zh_cn_no_reference(self):
        prompt = get_chat_system_prompt("zh_CN")
        assert "特征提取器参考" not in prompt
        assert "## 特征提取器参考" not in prompt

    def test_default_no_user_text_zh_hk_no_reference(self):
        prompt = get_chat_system_prompt("zh_HK")
        assert "特徵提取器參考" not in prompt
        assert "## 特徵提取器參考" not in prompt

    def test_triggered_by_training_keywords_en(self):
        prompt = get_chat_system_prompt("en", user_text="Which feature extractor should I use for training?")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_extractor_keywords_en(self):
        prompt = get_chat_system_prompt("en", user_text="What is GPFM?")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_model_architecture_en(self):
        prompt = get_chat_system_prompt("en", user_text="Tell me about MIL aggregators")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_encoder_keywords_en(self):
        prompt = get_chat_system_prompt("en", user_text="Which encoder is best?")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_foundation_model_en(self):
        prompt = get_chat_system_prompt("en", user_text="What foundation models are supported?")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_supported_components_en(self):
        prompt = get_chat_system_prompt("en", user_text="List supported classifiers")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_training_recommendation_en(self):
        prompt = get_chat_system_prompt("en", user_text="Recommend a training setup")
        assert "Feature Extractor Reference" in prompt

    def test_not_triggered_by_unrelated_text_en(self):
        prompt = get_chat_system_prompt("en", user_text="Hello, how are you?")
        assert "Feature Extractor Reference" not in prompt

    def test_not_triggered_by_dataset_question_en(self):
        prompt = get_chat_system_prompt("en", user_text="What datasets do I have?")
        assert "Feature Extractor Reference" not in prompt

    def test_triggered_by_chinese_training_keywords(self):
        prompt = get_chat_system_prompt("zh_CN", user_text="我想训练一个模型，该用哪个特征提取器？")
        assert "特征提取器参考" in prompt

    def test_triggered_by_chinese_extractor_keywords(self):
        prompt = get_chat_system_prompt("zh_CN", user_text="GPFM是什么？")
        assert "特征提取器参考" in prompt

    def test_triggered_by_traditional_chinese_training_keywords(self):
        prompt = get_chat_system_prompt("zh_HK", user_text="我想訓練一個模型，該用哪個特徵提取器？")
        assert "特徵提取器參考" in prompt

    def test_backward_compatibility_no_user_text_arg(self):
        prompt = get_chat_system_prompt("en")
        assert "Feature Extractor Reference" not in prompt

    def test_backward_compatibility_none_lang(self):
        prompt = get_chat_system_prompt(None)
        assert "You are PathLab Agent" in prompt
        assert "Feature Extractor Reference" not in prompt

    def test_triggered_by_classifier_keywords(self):
        prompt = get_chat_system_prompt("en", user_text="What classifiers are available?")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_aggregator_keywords(self):
        prompt = get_chat_system_prompt("en", user_text="Compare ABMIL and TransMIL")
        assert "Feature Extractor Reference" in prompt

    def test_triggered_by_segmentation_keywords(self):
        prompt = get_chat_system_prompt("en", user_text="Which segmentation backbone should I use?")
        assert "Feature Extractor Reference" in prompt

    def test_case_insensitive_triggering(self):
        prompt = get_chat_system_prompt("en", user_text="FEATURE EXTRACTOR options")
        assert "Feature Extractor Reference" in prompt

    def test_user_text_none_defaults_to_no_reference(self):
        prompt = get_chat_system_prompt("en", user_text=None)
        assert "Feature Extractor Reference" not in prompt

    def test_user_text_empty_string_defaults_to_no_reference(self):
        prompt = get_chat_system_prompt("en", user_text="")
        assert "Feature Extractor Reference" not in prompt
