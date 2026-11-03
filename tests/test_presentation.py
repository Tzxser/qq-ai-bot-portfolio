from bot.presentation.plain import format_answer, split_for_qq


def test_math_markup_becomes_copyable_plain_text():
    answer = format_answer(
        r"以 sin x 为例：\(x \in [-\pi/2, \pi/2]\)。\n"
        r"反函数是 \(\arcsin x\)，例如 \(\arcsin(1/2)=\pi/6\)。"
    )
    assert "x ∈ [-π/2, π/2]" in answer
    assert "arcsin(1/2)=π/6" in answer
    assert "\\(" not in answer and "\\pi" not in answer


def test_nested_fraction_keeps_grouping_and_sqrt():
    answer = format_answer(r"\[\frac{a+b}{c+d} + \sqrt{x+1}\]")
    assert "(a+b)/(c+d)" in answer
    assert "√(x+1)" in answer


def test_code_paths_and_markdown_are_not_globally_stripped():
    answer = format_answer("```cpp\nint **p; #include <x>\n```\n**标题** C:\\tmp\\x")
    assert "int **p; #include <x>" in answer
    assert "C:\\tmp\\x" in answer
    assert "标题" in answer
    assert "**标题**" not in answer


def test_currency_is_not_treated_as_dollar_math():
    assert format_answer("USD $5 and $20") == "USD $5 and $20"


def test_split_reports_long_answer_instead_of_silent_token_slice():
    result = split_for_qq("第一段\n\n" + "x" * 8000, limit=4000, max_parts=2)
    assert len(result.parts) == 2
    assert all(len(part) <= 4040 for part in result.parts)
    assert result.truncated is True
    assert "后续部分未发送" in result.parts[-1]
