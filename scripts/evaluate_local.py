#!/usr/bin/env python3
"""Run the deterministic, local GAILSPARTAN retrieval evaluation.

The evaluator creates a temporary Flask/SQLite application, indexes the
versioned public-demo fixtures as tiny text PDFs, evaluates the questions,
and optionally runs a stdlib-only concurrent retrieval smoke benchmark.  It
does not call a network service or require a model provider.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Iterable

from sqlalchemy.pool import NullPool


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = REPOSITORY_ROOT / "evaluation" / "public_demo_dataset.json"
BACKEND_ROOT = REPOSITORY_ROOT / "GAILSPARTAN"


def _ensure_backend_importable() -> None:
    """Make the existing backend package importable from any working folder."""

    backend_root = str(BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)


def load_dataset(path: Path = DEFAULT_DATASET_PATH) -> dict[str, Any]:
    """Load and validate the versioned public demo dataset."""

    with path.open("r", encoding="utf-8") as dataset_file:
        dataset = json.load(dataset_file)

    if not isinstance(dataset, dict):
        raise ValueError("The evaluation dataset must contain a JSON object.")
    if dataset.get("dataset_type") != "public-demo":
        raise ValueError("The evaluation dataset must be labeled public-demo.")

    documents = dataset.get("documents")
    questions = dataset.get("questions")
    if not isinstance(documents, list) or not documents:
        raise ValueError("The evaluation dataset must contain documents.")
    if not isinstance(questions, list) or not questions:
        raise ValueError("The evaluation dataset must contain questions.")

    document_ids: set[str] = set()
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("Each evaluation document must be an object.")
        document_id = document.get("id")
        filename = document.get("filename")
        passage = document.get("passage")
        if not all(isinstance(value, str) and value.strip() for value in (document_id, filename, passage)):
            raise ValueError("Each document needs non-empty id, filename, and passage fields.")
        if document_id in document_ids:
            raise ValueError(f"Duplicate evaluation document id: {document_id}")
        document_ids.add(document_id)

    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Each evaluation question must be an object.")
        if not isinstance(question.get("id"), str) or not question["id"].strip():
            raise ValueError("Each question needs a non-empty id.")
        if not isinstance(question.get("question"), str) or not question["question"].strip():
            raise ValueError("Each question needs a non-empty question field.")
        keywords = question.get("expected_source_keywords", [])
        if not isinstance(keywords, list) or not all(isinstance(item, str) for item in keywords):
            raise ValueError("expected_source_keywords must be a list of strings.")
        if not isinstance(question.get("should_abstain"), bool):
            raise ValueError("Each question needs a boolean should_abstain field.")

    return dataset


def _pdf_escape(text: str) -> bytes:
    """Escape the small subset needed by the fixture PDF content stream."""

    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", errors="replace")
    )


def make_text_pdf(text: str) -> bytes:
    """Create a tiny valid one-page PDF without adding a test dependency."""

    stream = b"BT /F1 12 Tf 72 720 Td (" + _pdf_escape(text) + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for index, object_body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode("ascii")
        pdf += object_body + b"\nendobj\n"

    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n".encode("ascii")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode("ascii")
    pdf += (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return pdf


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    """Return an interpolated percentile, or ``None`` for no observations."""

    ordered = sorted(values)
    if not ordered:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile_value must be between 0 and 100")
    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percentile_value / 100
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _normalise_keywords(values: Iterable[str]) -> list[str]:
    return [value.strip().casefold() for value in values if value.strip()]


def _source_matches_keywords(filename: str, keywords: Iterable[str]) -> bool:
    normalized_filename = filename.casefold()
    normalized_keywords = _normalise_keywords(keywords)
    return bool(normalized_keywords) and any(
        keyword in normalized_filename for keyword in normalized_keywords
    )


def _is_abstention(response: str, sources: list[dict[str, Any]], unsupported_answer: str) -> bool:
    return response == unsupported_answer and not sources


def _load_backend():
    """Import backend modules only while an evaluation run is being created."""

    _ensure_backend_importable()
    from backend.app import create_app
    from backend.extensions import db
    from backend.models import DocumentChunk, User
    from backend.rag import LocalRAGService, UNSUPPORTED_ANSWER, answer_from_matches

    return create_app, db, DocumentChunk, User, LocalRAGService, UNSUPPORTED_ANSWER, answer_from_matches


def _create_isolated_app(database_path: Path, create_app):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "gailspratan-evaluation-only",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "poolclass": NullPool,
                "connect_args": {"check_same_thread": False},
            },
            "RAG_CHUNK_SIZE": 600,
            "RAG_CHUNK_OVERLAP": 80,
            "RAG_TOP_K": 5,
        }
    )


def _create_user(db, User, username: str, email: str) -> int:
    from werkzeug.security import generate_password_hash

    user = User(
        username=username,
        email=email,
        password=generate_password_hash("evaluation-password"),
    )
    db.session.add(user)
    db.session.commit()
    return int(user.id)


def _index_documents(app, db, LocalRAGService, User, documents: list[dict[str, Any]], username: str) -> int:
    service = LocalRAGService(chunk_size=600, overlap=80)
    with app.app_context():
        user_id = _create_user(
            db,
            User,
            username=username,
            email=f"{username}@example.invalid",
        )
        for document in documents:
            service.index_pdf(
                user_id,
                make_text_pdf(document["passage"]),
                document["filename"],
            )
        db.session.commit()
    return user_id


def _evaluate_question(
    app,
    service,
    user_id: int,
    question: dict[str, Any],
    unsupported_answer: str,
    answer_from_matches,
    top_k: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    with app.app_context():
        matches = service.retrieve(user_id, question["question"], top_k=top_k)
        answer = answer_from_matches(question["question"], matches)
        retrieved_filenames = [
            str(getattr(getattr(chunk, "document", None), "filename", "unknown"))
            for chunk, _score in matches
        ]
    elapsed_ms = (time.perf_counter() - started) * 1000

    expected_source_keywords = question.get("expected_source_keywords", [])
    expected_answer_keywords = question.get("expected_answer_keywords", [])
    retrieval_hit = (
        _source_matches_keywords(retrieved_filenames[0], expected_source_keywords)
        if retrieved_filenames and expected_source_keywords
        else False
    )
    citation_hit = any(
        _source_matches_keywords(str(source.get("filename", "")), expected_source_keywords)
        for source in answer.sources
    ) if expected_source_keywords else False
    answer_text = answer.response.casefold()
    answer_keyword_hit = (
        bool(expected_answer_keywords)
        and all(keyword.casefold() in answer_text for keyword in expected_answer_keywords)
    )
    abstained = _is_abstention(answer.response, answer.sources, unsupported_answer)

    return {
        "id": question["id"],
        "question": question["question"],
        "expected_abstain": question["should_abstain"],
        "abstained": abstained,
        "retrieval_hit": retrieval_hit,
        "citation_hit": citation_hit,
        "answer_keyword_hit": answer_keyword_hit,
        "retrieved_filenames": retrieved_filenames,
        "sources": answer.sources,
        "response": answer.response,
        "latency_ms": elapsed_ms,
    }


def _metric_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _build_metrics(results: list[dict[str, Any]], latency_ms: list[float]) -> dict[str, Any]:
    supported = [item for item in results if not item["expected_abstain"]]
    expected_abstentions = [item for item in results if item["expected_abstain"]]
    correct_abstentions = [item for item in expected_abstentions if item["abstained"]]
    false_abstentions = [item for item in supported if item["abstained"]]

    return {
        "question_count": len(results),
        "supported_question_count": len(supported),
        "expected_abstention_count": len(expected_abstentions),
        "retrieval_hits": sum(item["retrieval_hit"] for item in supported),
        "retrieval_hit_rate": _metric_rate(
            sum(item["retrieval_hit"] for item in supported), len(supported)
        ),
        "citation_hits": sum(item["citation_hit"] for item in supported),
        "citation_source_hit_rate": _metric_rate(
            sum(item["citation_hit"] for item in supported), len(supported)
        ),
        "answer_keyword_hits": sum(item["answer_keyword_hit"] for item in supported),
        "answer_keyword_hit_rate": _metric_rate(
            sum(item["answer_keyword_hit"] for item in supported), len(supported)
        ),
        "correct_abstentions": len(correct_abstentions),
        "abstention_accuracy": _metric_rate(
            len(correct_abstentions), len(expected_abstentions)
        ),
        "false_abstentions": len(false_abstentions),
        "false_abstention_rate": _metric_rate(len(false_abstentions), len(supported)),
        "latency_ms": {
            "count": len(latency_ms),
            "p50": percentile(latency_ms, 50),
            "p95": percentile(latency_ms, 95),
            "min": min(latency_ms) if latency_ms else None,
            "max": max(latency_ms) if latency_ms else None,
        },
    }


def _run_benchmark_worker(
    app,
    service,
    user_id: int,
    questions: list[str],
    requests_per_user: int,
) -> dict[str, Any]:
    timings: list[float] = []
    errors: list[str] = []
    for request_index in range(requests_per_user):
        query = questions[request_index % len(questions)]
        started = time.perf_counter()
        try:
            with app.app_context():
                result = service.answer(user_id, query)
                if not result.response:
                    raise RuntimeError("empty response")
        except Exception as exc:  # report a worker failure without hiding it
            errors.append(f"{type(exc).__name__}: {exc}")
        else:
            timings.append((time.perf_counter() - started) * 1000)
    return {"timings": timings, "errors": errors}


def run_concurrent_benchmark(
    app,
    db,
    User,
    LocalRAGService,
    documents: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    concurrency: int,
    requests_per_user: int,
) -> dict[str, Any]:
    """Run local retrieval requests from independent users in parallel."""

    if concurrency <= 0 or requests_per_user <= 0:
        raise ValueError("concurrency and requests_per_user must be positive")

    supported_queries = [
        question["question"] for question in questions if not question["should_abstain"]
    ]
    if not supported_queries:
        raise ValueError("The dataset needs at least one supported question for benchmarking.")

    service = LocalRAGService(chunk_size=600, overlap=80)
    user_ids: list[int] = []
    with app.app_context():
        for index in range(concurrency):
            username = f"benchmark-user-{index}"
            user_ids.append(
                _create_user(
                    db,
                    User,
                    username=username,
                    email=f"{username}@example.invalid",
                )
            )
            for document in documents:
                service.index_pdf(
                    user_ids[-1],
                    make_text_pdf(document["passage"]),
                    document["filename"],
                )
        db.session.commit()

    started = time.perf_counter()
    timings: list[float] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _run_benchmark_worker,
                app,
                service,
                user_id,
                supported_queries,
                requests_per_user,
            )
            for user_id in user_ids
        ]
        for future in as_completed(futures):
            result = future.result()
            timings.extend(result["timings"])
            errors.extend(result["errors"])
    wall_time_s = time.perf_counter() - started

    completed = len(timings)
    requested = concurrency * requests_per_user
    return {
        "concurrency": concurrency,
        "requests_per_user": requests_per_user,
        "requested_requests": requested,
        "completed_requests": completed,
        "error_count": len(errors),
        "errors": errors,
        "wall_time_seconds": wall_time_s,
        "throughput_requests_per_second": completed / wall_time_s if wall_time_s else None,
        "latency_ms": {
            "count": completed,
            "p50": percentile(timings, 50),
            "p95": percentile(timings, 95),
            "min": min(timings) if timings else None,
            "max": max(timings) if timings else None,
        },
    }


def run_evaluation(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    *,
    concurrency: int = 0,
    requests_per_user: int = 0,
) -> dict[str, Any]:
    """Run evaluation and optionally the concurrent smoke benchmark."""

    dataset = load_dataset(dataset_path)
    fallback_database_path = BACKEND_ROOT / "chatbot.sqlite3"
    fallback_existed = fallback_database_path.exists()
    (
        create_app,
        db,
        _DocumentChunk,
        User,
        LocalRAGService,
        unsupported_answer,
        answer_from_matches,
    ) = _load_backend()
    try:
        with tempfile.TemporaryDirectory(prefix="gailspratan-evaluation-") as temp_dir:
            database_path = Path(temp_dir) / "evaluation.sqlite3"
            app = _create_isolated_app(database_path, create_app)
            user_id = _index_documents(
                app,
                db,
                LocalRAGService,
                User,
                dataset["documents"],
                username="evaluation-user",
            )
            service = LocalRAGService(chunk_size=600, overlap=80)
            results = [
                _evaluate_question(
                    app,
                    service,
                    user_id,
                    question,
                    unsupported_answer,
                    answer_from_matches,
                    top_k=5,
                )
                for question in dataset["questions"]
            ]
            metrics = _build_metrics(
                results,
                [item["latency_ms"] for item in results],
            )

            benchmark = None
            if concurrency or requests_per_user:
                if concurrency <= 0 or requests_per_user <= 0:
                    raise ValueError(
                        "concurrency and requests_per_user must both be positive when benchmarking"
                    )
                benchmark = run_concurrent_benchmark(
                    app,
                    db,
                    User,
                    LocalRAGService,
                    dataset["documents"],
                    dataset["questions"],
                    concurrency,
                    requests_per_user,
                )

            return {
                "dataset": {
                    "name": dataset.get("name"),
                    "version": dataset.get("version"),
                    "path": str(dataset_path),
                },
                "metrics": metrics,
                "questions": results,
                "benchmark": benchmark,
            }
    finally:
        # Windows does not allow TemporaryDirectory to remove an SQLite file
        # while pooled connections from worker threads are still open.
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass
        # Importing the existing app factory creates its historical fallback
        # database at module import time. Remove only a file this run created.
        if not fallback_existed and fallback_database_path.exists():
            try:
                fallback_database_path.unlink()
            except OSError:
                pass


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_report(report: dict[str, Any]) -> str:
    """Render a concise human-readable report."""

    metrics = report["metrics"]
    latency = metrics["latency_ms"]
    lines = [
        f"GAILSPARTAN local evaluation: {report['dataset']['name']} v{report['dataset']['version']}",
        f"Questions: {metrics['question_count']} ({metrics['supported_question_count']} supported)",
        f"Retrieval hit rate: {metrics['retrieval_hits']}/{metrics['supported_question_count']} ({_format_rate(metrics['retrieval_hit_rate'])})",
        f"Citation/source hit rate: {metrics['citation_hits']}/{metrics['supported_question_count']} ({_format_rate(metrics['citation_source_hit_rate'])})",
        f"Answer keyword hit rate: {metrics['answer_keyword_hits']}/{metrics['supported_question_count']} ({_format_rate(metrics['answer_keyword_hit_rate'])})",
        "Abstention: "
        f"{metrics['correct_abstentions']}/{metrics['expected_abstention_count']} expected unsupported questions correctly abstained "
        f"({_format_rate(metrics['abstention_accuracy'])}); "
        f"false abstentions on supported questions: {metrics['false_abstentions']} "
        f"({_format_rate(metrics['false_abstention_rate'])})",
        f"Evaluation latency (ms): p50={_format_ms(latency['p50'])} p95={_format_ms(latency['p95'])} "
        f"min={_format_ms(latency['min'])} max={_format_ms(latency['max'])}",
    ]
    if report.get("benchmark") is not None:
        benchmark = report["benchmark"]
        benchmark_latency = benchmark["latency_ms"]
        lines.extend(
            [
                "Concurrent smoke benchmark:",
                f"  users={benchmark['concurrency']} requests/user={benchmark['requests_per_user']} "
                f"completed={benchmark['completed_requests']}/{benchmark['requested_requests']} errors={benchmark['error_count']}",
                f"  throughput={_format_ms(benchmark['throughput_requests_per_second'])} requests/s "
                f"wall={benchmark['wall_time_seconds']:.3f}s",
                f"  latency (ms): p50={_format_ms(benchmark_latency['p50'])} "
                f"p95={_format_ms(benchmark_latency['p95'])} min={_format_ms(benchmark_latency['min'])} "
                f"max={_format_ms(benchmark_latency['max'])}",
            ]
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to a public-demo JSON dataset (default: evaluation/public_demo_dataset.json)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="Concurrent local users for the optional smoke benchmark (default: disabled)",
    )
    parser.add_argument(
        "--requests-per-user",
        type=int,
        default=0,
        help="Sequential retrieval requests issued by each benchmark user (default: disabled)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete report as JSON instead of human-readable text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_evaluation(
            args.dataset,
            concurrency=args.concurrency,
            requests_per_user=args.requests_per_user,
        )
    except (OSError, ValueError, ImportError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
