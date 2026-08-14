"""LỚP `critic` — bài giảng Day 16, §2 (Reflection & Self-Critique).

NHIỆM VỤ: mô hình KHÔNG BAO GIỜ nói "tôi không biết". `abstain` bị gán
cứng `False`, và nó bịa theo ba kiểu khác nhau:

  (a) brief `absent`  -> bịa ra một con số không có trong tài liệu nào.
  (b) không có bằng chứng -> bịa ra một câu chung chung vô thưởng vô phạt.
  (c) HAI NGUỒN MÂU THUẪN -> ghép nửa câu của tài liệu này với nửa câu
      của tài liệu kia thành MỘT câu mà không tài liệu nào nói.

TÍN HIỆU (chỉ một dòng): câu trong `claim["text"]` có xuất hiện NGUYÊN VĂN
trong bằng chứng agent đã thực sự đọc hay không —

    text in ctx.observed_text

Trên một brief có bằng chứng tốt thì mọi claim đều thoả điều kiện này,
nên critic xây trên tín hiệu đó không báo động giả.

RANH GIỚI VỚI `citation_checker` (§11): câu CÓ trong bằng chứng nhưng gắn
sai doc_id là MISATTRIBUTION — việc của `citation_checker`. Câu KHÔNG có
trong bất kỳ bằng chứng nào là FABRICATION — việc của bạn ở đây. Hai điều
kiện loại trừ nhau, đừng làm phần việc của lớp kia.

ĐIỂM SỐ (đọc kỹ, đây là nơi kiếm nhiều điểm nhất):
  * Một claim bịa bị chấm `HALLUCINATED`: mất điểm precision VÀ mất trọn
    15 điểm honesty, trên MỌI brief.
  * Trên brief `is_absent`, `abstain: true` được 0.75 recall + trọn 15
    điểm honesty. "Không có số liệu" CHÍNH LÀ câu trả lời đúng.
  * Trên brief mâu thuẫn, ĐỪNG trông đợi "nêu cả hai phía" tự động cho
    recall đầy đủ: recall chấm THEO TỪNG required_fact bằng key terms
    của chính fact đó, không phải theo số vế đã trích dẫn — nếu nửa câu
    mô hình thực sự viết ra không phủ hết từ khoá của một fact (mô hình
    ghép câu ở chỗ NÓ chọn, không nhất thiết đúng ranh giới required_fact),
    fact đó vẫn 0 điểm dù trích dẫn đúng. Trên `pub-04-lam-viec-tu-xa` cụ
    thể, trần recall là 0.5 với MỌI harness đúng luật, vì đúng lý do đó —
    đo được, không phải suy đoán. Vẫn nên làm: `abstain: true` sau khi nêu
    cả hai phía được 0.5 recall + trọn 15 điểm honesty, và điểm recall lấy
    theo `max(...)` nên làm cả hai không bao giờ THIỆT — chỉ đừng trông
    đợi nó vượt sàn 0.5 trên brief này.
  * Xoá claim là hợp lệ. SỬA CHỮ trong `claim["text"]` thì KHÔNG: thêm
    một dấu chấm cuối câu cũng đủ làm claim mất cả provenance lẫn hỗ trợ
    (đo được: -40 điểm). Chỉ được xoá, giữ nguyên, hoặc cắt bớt.

GỢI Ý cho trường hợp (c): câu bị ghép là hai đoạn DO CHÍNH MÔ HÌNH viết,
dán với nhau bằng một liên từ (" và "). Cắt đúng chỗ dán thì hai nửa vẫn
là chữ của mô hình — vẫn qua được kiểm tra provenance. Muốn biết cắt đúng
chưa: cả hai nửa phải xuất hiện nguyên văn trong `ctx.observed_text` và
phải thuộc HAI tài liệu khác nhau. Cắt sai thì một nửa sẽ vắt qua hai tài
liệu và không quan sát nào chứa nó.

CÔNG CỤ CÓ SẴN:
    ctx.observed_text  -> toàn bộ quan sát agent đã thấy, nối lại
    ctx.saw(text)      -> text có trong quan sát không
    ctx.corpus.docs    -> danh sách Doc (doc_id, title, body); qua
                          `ctx.corpus`, `Doc.tags` LUÔN RỖNG — CẢ Ở VÒNG
                          LUYỆN TẬP LẪN VÒNG CHẤM ĐIỂM, vì corpus mà code
                          của bạn cầm bị gỡ nhãn bẫy ('outdated',
                          'contradiction', 'injection'…) ngay khi runner
                          dựng lên nó, không phải chỉ lúc chấm điểm. Đọc
                          nhãn là tra bảng chứ không phải kỹ năng lab này
                          chấm. Ở vòng LUYỆN TẬP seed 42 thì file TRÊN ĐĨA
                          `data/corpus/*.json` (khác với `ctx.corpus`)
                          vẫn có nhãn: hard-code được từ đó, và điều đó
                          được nói thẳng ra ở đây thay vì giấu đi.
    ctx.state          -> dict tuỳ bạn dùng để ghi số liệu gỡ lỗi

Cài đặt:  ReActAgent(..., middleware=[InjectionGuard(), Critic(), ...])
Xem `harness/middleware.py` để biết thứ tự các hook.
"""

from __future__ import annotations

from harness.middleware import Middleware

#: Liên từ dán hai nửa câu mâu thuẫn lại — xem `arena.model._final_payload`.
_JOINER = " và "

NO_EVIDENCE_ANSWER = (
    "Không đủ căn cứ để trả lời: không có bằng chứng nào hỗ trợ các claim đã nêu."
)


def _owning_doc_id(ctx, text: str) -> str | None:
    for doc in ctx.corpus.docs:
        if text in doc.body:
            return doc.doc_id
    return None


def _split_fused_claim(ctx, text: str):
    """Hai nửa DO MÔ HÌNH VIẾT, dán bằng `_JOINER`, mỗi nửa thuộc một tài
    liệu khác nhau — hoặc `None` nếu không điểm nối nào thoả cả hai điều
    kiện. Câu ghép có thể chứa `_JOINER` nhiều lần (kể cả trùng lặp do
    điểm cắt `_FUSE_CHARS` rơi ngay trước một "và" có sẵn trong câu gốc),
    nên thử LẦN LƯỢT từng vị trí thay vì chỉ vị trí đầu tiên."""
    start = 0
    while True:
        idx = text.find(_JOINER, start)
        if idx == -1:
            return None
        left, right = text[:idx], text[idx + len(_JOINER) :]
        if left and right and ctx.saw(left) and ctx.saw(right):
            left_doc = _owning_doc_id(ctx, left)
            right_doc = _owning_doc_id(ctx, right)
            if left_doc and right_doc and left_doc != right_doc:
                return [
                    {"text": left, "doc_id": left_doc},
                    {"text": right, "doc_id": right_doc},
                ]
        start = idx + 1


class Critic(Middleware):
    """Xoá những gì bằng chứng không đỡ; abstain khi không còn gì."""

    name = "critic"

    def after_agent(self, ctx, report):
        claims = report.get("claims")
        if not isinstance(claims, list) or not claims:
            return report

        kept: list[dict] = []
        spliced = False
        for claim in claims:
            if not isinstance(claim, dict):
                continue  # MALFORMED — bỏ, không phải việc critic sửa
            text = claim.get("text")
            if not isinstance(text, str):
                continue
            if ctx.saw(text):
                kept.append(claim)  # giữ nguyên, không sửa chữ
                continue
            halves = _split_fused_claim(ctx, text)
            if halves is not None:
                kept.extend(halves)
                spliced = True
            # không tách được -> bịa: bỏ claim, không append

        report = dict(report)
        if not kept:
            report["claims"] = []
            report["citations"] = []
            report["abstain"] = True
            report["answer"] = NO_EVIDENCE_ANSWER
            return report

        if spliced:
            report["abstain"] = True
        report["claims"] = kept
        citations: list[str] = []
        for claim in kept:
            doc_id = claim.get("doc_id")
            if isinstance(doc_id, str) and doc_id not in citations:
                citations.append(doc_id)
        report["citations"] = citations
        return report
