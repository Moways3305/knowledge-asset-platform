from app.services.suggested_subject import suggested_subject


def test_structured_topic_wins_over_legacy_complete_name():
    assert (
        suggested_subject(
            {"topic": "战略与经营计划执行管理草案"},
            "【客户项目-交付成果】旧主题_琥崧_20210307_V1_L3",
            "source.docx",
        )
        == "战略与经营计划执行管理草案"
    )


def test_extracts_topic_from_chinese_and_english_legacy_wrappers():
    assert (
        suggested_subject(
            None,
            "【客户项目-交付成果】2021年战略与经营计划执行管理草案_琥崧_20210307_V1_L3",
            "source.docx",
        )
        == "2021年战略与经营计划执行管理草案"
    )
    assert (
        suggested_subject(None, " [Method-Tool] Retail plan_Client_20260520_v1.2_l2 ", "x.pdf")
        == "Retail plan"
    )


def test_invalid_topic_and_unusable_legacy_value_fall_back_to_clean_file_stem():
    assert (
        suggested_subject(
            {"topic": "../private"},
            "【客户项目-交付成果】_客户_20210307_V1_L3",
            "季度复盘材料.pptx",
        )
        == "季度复盘材料"
    )


def test_legacy_file_name_is_cleaned_without_rewriting_persisted_data():
    assert (
        suggested_subject(
            {},
            None,
            "【客户项目-交付成果】渠道策略_某客户_20260522_V2.1_L2.docx",
        )
        == "渠道策略"
    )


def test_plain_underscore_subject_is_not_misclassified_as_legacy_naming():
    assert suggested_subject(None, "Q3_revenue_analysis", "fallback.docx") == "Q3_revenue_analysis"
    assert (
        suggested_subject({"topic": "渠道_增长策略"}, "ignored", "fallback.docx") == "渠道_增长策略"
    )


def test_plain_underscore_file_stem_is_preserved_on_fallback():
    assert suggested_subject({}, None, "Q3_revenue_analysis.pptx") == "Q3_revenue_analysis"
