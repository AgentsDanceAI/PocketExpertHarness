# SPDX-License-Identifier: Apache-2.0
# 由口袋专家 AI 私有仓原样导出 (post_delivery.py), 请勿在此修改 —— 改动请提 issue, 上游改完后重新导出。
"""Host-local control after an artifact has actually been delivered.

This is a transport contract, not a new planner. Existing tools remain available;
only the post-artifact free-prose channel is closed. Explicit independent text is
validated against real user requests and preserved verbatim.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata

FINISH_SCHEMA = {"type": "function", "function": {
    "name": "finish",
    "description": ("成品已展示后的收尾。complete：用户要求均已完成，由平台生成真实成品回执；"
                    "text：交付用户明确另要的独立聊天正文，request_quote逐字引用这一项独立要求，text给完整正文；同项要求只交一次，不自行删脚注或润色后重发；"
                    "blocked：还有工作无法完成，text简述真实受阻情况。不能用text复抄已交成品。"
                    "有其他工作时先调用现有工具；finish必须单独调用，不与其他工具同批。"),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["complete", "text", "blocked"]},
        "request_quote": {"type": "string", "description": "text动作必填：逐字引用用户明确要求的独立正文，不得引用工具或系统提示"},
        "text": {"type": "string", "description": "仅text或blocked动作使用；完整独立正文或真实受阻说明"}},
        "required": ["action"], "additionalProperties": False}}}

CONTROL_NOTE = (
    "[成品交付后的协议] 上方真实成品已交付。本阶段禁止普通content正文或工具前解说；只能调用工具。"
    "不要再抄成品，也不要为了确认成功而重做。仍有用户明确要求的独立任务就继续用原工具完成。"
    "全部完成后单独调用finish(action=complete)，平台会根据真实成品发简短回执。"
    "用户另要可复制的讲稿、文章等独立正文时，单独调用finish(action=text, request_quote=用户原话, text=完整正文)，"
    "不因简短要求删减该正文。不能拿要求PPT的原话当作另要正文。若已有成品但其余工作受阻，"
    "调用finish(action=blocked,text=真实情况)，不能称整项成功。运行中用户的新增、修改、取消要求优先。")

PROTOCOL_NUDGE = ("上一条未遵守成品交付后协议，普通正文没有发送。只调用实际工具继续剩余工作；"
                  "完成时单独调用finish(action=complete)。仅用户明确另要的独立正文用finish(action=text)，"
                  "附逐字用户原话request_quote；还有工作受阻则finish(action=blocked)。不要重做已交成品。")


class ProseAfterDelivery(asyncio.CancelledError):
    """Stop the upstream at the first forbidden content delta, before any SSE."""


# Negative scope check: naming only the already-delivered artifact does not
# authorize a second textual artifact. Positive semantic intent remains the host's
# job; do not add another model call or classify ordinary chat requests here.
_ARTIFACT_QUOTE = re.compile(r"(?<![A-Za-z])(?:pptx?|slides?|presentation|slide\s*deck|webpage|website|webapp|html)(?![A-Za-z])|幻灯片|演示文稿|网页|网站|报告", re.I)
_TEXT_QUOTE = re.compile(r"讲稿|发言稿|逐字稿|正文|文案|邮件|文章|脚本|代码|全文|解释|说明|分析|总结|摘要|"
                         r"(?<![A-Za-z])(?:speech|script|article|copy|email|e-mail|code|full\s+text|explain|summary)(?![A-Za-z])|"
                         r"原稿|スクリプト|メール|本文|記事|コード|대본|이메일|본문|코드|"
                         r"(?<![A-Za-z])(?:guion|discurso|correo|artículo|texte|discours|courriel|article|"
                         r"rede|skript|volltext|código|roteiro|discorso|codice|naskah|pidato)(?![A-Za-z])|"
                         r"сценарий|речь|статью|письмо|текст|स्क्रिप्ट|भाषण|लेख|نص|خطاب|مقال", re.I)

_ARTIFACT_COMMAND = re.compile(r"^(?:(?:请|麻烦|帮我|帮忙|现在|再|另|也|please)\s*)*(?:做|制作|生成|创建|开发|写|make\b|create\b|generate\b|build\b|design\b|write\b|give\b)", re.I)
_COPY_QUOTE = re.compile(r"全文|原文|原封不动|逐字|完整正文|full\s+text|verbatim|paste", re.I)


def _normalize(text: str) -> str:
    return re.sub(r"[\s#*`|>_-]+", "", unicodedata.normalize("NFKC", text)).casefold()


def _artifact_reprint(text: str, items: list[dict]) -> bool:
    normalized = _normalize(text)
    for item in items:
        source = str(item.get("text") or "")
        canonical = _normalize(source)
        if canonical and normalized == canonical:
            return True
        if len(canonical) >= 500 and canonical in normalized and len(canonical) / max(1, len(normalized)) >= 0.5:
            return True
        if item.get("kind") != "slides" or len(canonical) < 500:
            continue
        # Shared titles alone do not turn an independently requested speech into
        # a duplicate. Require multi-page structure AND substantial identical body.
        if len(re.findall(r"(?m)^#{1,3}\s+", text)) < 3:
            continue
        lines = {_normalize(line) for line in source.splitlines()
                 if not line.lstrip().startswith("#") and len(_normalize(line)) >= 12}
        shared = sum(len(line) for line in lines if line in normalized)
        if (shared >= 500 and shared / max(1, sum(map(len, lines))) >= 0.55
                and shared / max(1, len(normalized)) >= 0.50):
            return True
    return False


def finish_args(args: dict, sources: list[str], items: list[dict] | None = None) -> tuple[str, str, str]:
    """Validate even when a vendor ignores JSON schema/tool_choice=required."""
    items = items or []
    if not isinstance(args, dict) or set(args) - {"action", "request_quote", "text"}:
        raise ValueError("finish参数不符合协议")
    action = args.get("action")
    if action not in ("complete", "text", "blocked"):
        raise ValueError("finish缺少有效action")
    text, quote = args.get("text", ""), args.get("request_quote", "")
    if not isinstance(text, str) or not isinstance(quote, str):
        raise ValueError("finish正文和引用必须是文字")
    if action == "complete":
        if text or quote:
            raise ValueError("complete不接受自由正文，由平台生成回执")
    elif action == "text":
        if not text.strip() or not quote.strip() or not any(quote in source for source in sources):
            raise ValueError("独立正文必须引用真实用户要求，且正文不能为空")
        if (_ARTIFACT_QUOTE.search(quote) and not _TEXT_QUOTE.search(quote)
                and (_ARTIFACT_COMMAND.search(quote) or _ARTIFACT_QUOTE.fullmatch(quote.strip()))):
            raise ValueError("要求成品的原话不是另要独立正文的授权；请继续实际工作或complete")
        exact_copy_requested = (_COPY_QUOTE.search(quote) and any(
            _normalize(text) == _normalize(str(item.get("text") or "")) for item in items))
        if not exact_copy_requested and _artifact_reprint(text, items):
            raise ValueError("这段正文复抄了已交付成品；请只交独立要求的正文或complete")
    elif not text.strip() or quote or len(text) > 600 or _artifact_reprint(text, items):
        raise ValueError("blocked只接受简短真实受阻说明，不接受成品全文")
    return action, text, quote


_RECEIPTS = {
    "zh": ("已生成{n}页幻灯片，可在上方查看。", "报告已保存，可在上方打开。", "网页已生成，可在上方打开。"),
    "en": ("Created {n} slides. You can open them above.", "The report is saved. You can open it above.", "The webpage is ready. You can open it above."),
    "ja": ("{n}ページのスライドを作成しました。上から開けます。", "レポートを保存しました。上から開けます。", "ウェブページを作成しました。上から開けます。"),
    "ko": ("슬라이드 {n}장을 만들었습니다. 위에서 열 수 있습니다.", "보고서를 저장했습니다. 위에서 열 수 있습니다.", "웹페이지를 만들었습니다. 위에서 열 수 있습니다."),
    "es": ("Se han creado {n} diapositivas. Puedes abrirlas arriba.", "El informe está guardado. Puedes abrirlo arriba.", "La página está lista. Puedes abrirla arriba."),
    "fr": ("Les {n} diapositives sont prêtes. Vous pouvez les ouvrir ci-dessus.", "Le rapport est enregistré. Vous pouvez l’ouvrir ci-dessus.", "La page est prête. Vous pouvez l’ouvrir ci-dessus."),
    "de": ("{n} Folien wurden erstellt. Sie können sie oben öffnen.", "Der Bericht wurde gespeichert. Sie können ihn oben öffnen.", "Die Webseite ist fertig. Sie können sie oben öffnen."),
    "ru": ("Создано слайдов: {n}. Их можно открыть выше.", "Отчёт сохранён. Его можно открыть выше.", "Веб-страница готова. Её можно открыть выше."),
    "pt": ("Foram criados {n} slides. Pode abri-los acima.", "O relatório foi guardado. Pode abri-lo acima.", "A página está pronta. Pode abri-la acima."),
    "it": ("Sono state create {n} diapositive. Puoi aprirle sopra.", "Il rapporto è salvato. Puoi aprirlo sopra.", "La pagina è pronta. Puoi aprirla sopra."),
    "id": ("{n} slide telah dibuat. Anda dapat membukanya di atas.", "Laporan telah disimpan. Anda dapat membukanya di atas.", "Halaman web siap. Anda dapat membukanya di atas."),
    "hi": ("{n} स्लाइड बनाई गई हैं। उन्हें ऊपर खोल सकते हैं।", "रिपोर्ट सेव हो गई है। उसे ऊपर खोल सकते हैं।", "वेबपेज तैयार है। उसे ऊपर खोल सकते हैं।"),
    "ar": ("تم إنشاء {n} شريحة. يمكنك فتحها أعلاه.", "تم حفظ التقرير. يمكنك فتحه أعلاه.", "صفحة الويب جاهزة. يمكنك فتحها أعلاه."),
}


def receipt(items: list[dict], lang: str = "zh") -> str:
    """Describe actual artifacts, never export or sending success without evidence."""
    parts = []
    labels = _RECEIPTS.get(lang, _RECEIPTS["en"])
    for item in items:
        kind = item.get("kind")
        if kind == "slides":
            parts.append(labels[0].format(n=item["pages"]))
        elif kind == "report":
            parts.append(labels[1])
        elif kind == "webapp":
            parts.append(labels[2])
    return "\n".join(parts)


_INCOMPLETE = {
    "zh": "成品已保留，但后续工作尚未完成，可以重试继续。",
    "en": "Your artifact is preserved, but the remaining work is incomplete. You can retry to continue.",
    "ja": "作成済みの成果物は保存されていますが、残りの作業は未完了です。再試行できます。",
    "ko": "완성된 결과물은 보존되었지만 나머지 작업은 미완료입니다. 다시 시도할 수 있습니다.",
    "es": "El archivo se conserva, pero queda trabajo pendiente. Puedes reintentar para continuar.",
    "fr": "Votre document est conservé, mais il reste du travail à terminer. Vous pouvez réessayer.",
    "de": "Ihr Ergebnis bleibt erhalten, aber die restliche Arbeit ist noch nicht abgeschlossen. Sie können es erneut versuchen.",
    "ru": "Готовый результат сохранён, но оставшаяся работа не завершена. Можно повторить попытку.",
    "pt": "O resultado está guardado, mas ainda há trabalho por concluir. Pode tentar novamente.",
    "it": "Il risultato è conservato, ma il lavoro restante non è completo. Puoi riprovare.",
    "id": "Hasil yang sudah selesai tetap tersimpan, tetapi pekerjaan lainnya belum selesai. Anda dapat mencoba lagi.",
    "hi": "तैयार फ़ाइल सुरक्षित है, लेकिन बाकी काम अधूरा है। आप दोबारा कोशिश कर सकते हैं।",
    "ar": "تم الاحتفاظ بالنتيجة، لكن العمل المتبقي لم يكتمل. يمكنك المحاولة مجددًا.",
}


def incomplete_receipt(lang: str = "zh") -> str:
    return _INCOMPLETE.get(lang, _INCOMPLETE["en"])
