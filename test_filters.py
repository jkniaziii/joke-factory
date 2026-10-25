"""Unit tests for the pure filtering logic (no network/credentials)."""
from filters import (
    Candidate,
    is_duplicate,
    is_text_joke,
    normalize_text,
    passes_reddit_gate,
    prefilter,
)


def reddit(text="why did the x cross the y? because z.", ident="reddit-a1",
           score=100, comments=50):
    return Candidate(text=text, identifier=ident, source="reddit",
                     score=score, comments=comments)


def jokeapi(text="a dark one-liner that is clearly a joke here", ident="jokeapi-7"):
    return Candidate(text=text, identifier=ident, source="jokeapi")


# --- normalize_text ---
def test_normalize_collapses_punct_and_case_and_space():
    a = normalize_text("Why did the  CHICKEN...  cross?!")
    b = normalize_text("why did the chicken cross")
    assert a == b


# --- is_text_joke ---
def test_rejects_empty_and_short():
    assert not is_text_joke("")
    assert not is_text_joke("short")


def test_rejects_bare_link():
    assert not is_text_joke("https://example.com/image.png")


def test_accepts_real_joke():
    assert is_text_joke("why did the skeleton not go to the party? no body.")


# --- passes_reddit_gate ---
def test_reddit_gate_blocks_low_engagement():
    assert not passes_reddit_gate(reddit(score=9, comments=50), 10, 10)
    assert not passes_reddit_gate(reddit(score=50, comments=9), 10, 10)


def test_reddit_gate_passes_at_threshold():
    assert passes_reddit_gate(reddit(score=10, comments=10), 10, 10)


def test_jokeapi_skips_gate():
    # No score/comments, but curated — must pass the gate.
    assert passes_reddit_gate(jokeapi(), 10, 10)


# --- is_duplicate ---
def test_dup_by_identifier():
    c = reddit(ident="reddit-dup")
    assert is_duplicate(c, {"reddit-dup"}, set())


def test_dup_by_normalized_text():
    c = reddit(text="Why Did The X Cross?!")
    assert is_duplicate(c, set(), {normalize_text("why did the x cross")})


def test_not_duplicate_when_fresh():
    assert not is_duplicate(reddit(), set(), set())


# --- prefilter (integration of the pure pieces) ---
def test_prefilter_full_pipeline():
    candidates = [
        reddit(text="good joke one about something dark here", ident="reddit-1"),
        reddit(text="low effort", ident="reddit-2", score=5, comments=2),  # short + low
        reddit(text="good joke one about something dark here", ident="reddit-3"),  # text dup of 1
        jokeapi(text="a curated dark one-liner joke present", ident="jokeapi-9"),
    ]
    kept = prefilter(
        candidates,
        min_score=10,
        min_comments=10,
        seen_identifiers=set(),
        seen_norm_texts=set(),
    )
    idents = [c.identifier for c in kept]
    assert idents == ["reddit-1", "jokeapi-9"]


def test_prefilter_respects_already_seen():
    candidates = [reddit(ident="reddit-1")]
    kept = prefilter(
        candidates,
        min_score=10,
        min_comments=10,
        seen_identifiers={"reddit-1"},
        seen_norm_texts=set(),
    )
    assert kept == []
