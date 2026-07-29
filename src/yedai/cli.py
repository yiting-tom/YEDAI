"""yedai CLI。"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .embedding import CachedEmbedder, EmbeddingError, HttpEmbeddingClient
from .entities import EntityDictionary, EntitySourceError
from .formats import FULL, INTACT, NONE, PARTIAL, check_coverage, load_samples
from .fulltext import ConceptFileMissing, ConceptNotFound, ConceptPathEscape, load_concept
from .index import Index, build_index
from .queries import (
    DEFAULT_MIX,
    generate as generate_queries,
    load as load_queries,
    render as render_queries,
)
from .search import MODES, ModeResult, ModeUnavailable, Searcher, VectorSearcher
from .telemetry import TelemetryStore, build_report
from .tokenizer import Tokenizer
from .vectors import CorpusLeakGuard, VectorStore, guard_corpus_leaves_process

app = typer.Typer(add_completion=False, help="OKF bundle 關鍵字檢索 baseline harness（A/B/C 消融）")
console = Console()
err = Console(stderr=True)

ConfigOpt = typer.Option(None, "--config", "-c", help="設定檔路徑（YAML）")


def _config(path: Optional[Path]) -> Config:
    try:
        return Config.load(path)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]設定錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc


def _dictionary(cfg: Config) -> EntityDictionary:
    try:
        return EntityDictionary.from_config(cfg)
    except (FileNotFoundError, EntitySourceError) as exc:
        # 畸形的來源檔要當場停下來。載入一半的字典比沒有字典更糟——
        # 模式 C 會安靜地變差，而那看起來就像「字典沒有用」。
        err.print(f"[red]字典錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc


def _load_dotenv(path: Path = Path(".env")) -> None:
    """把 `.env` 讀進環境變數。已存在的變數不覆蓋——explicit export 應該贏過檔案。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _embedder(cfg: Config) -> CachedEmbedder:
    _load_dotenv()
    e = cfg.embedding
    client = HttpEmbeddingClient(
        base_url=e["base_url"],
        model=e["model"],
        dim=int(e["dim"]),
        api_key_env=e["api_key_env"],
        batch_size=int(e.get("batch_size", 32)),
        timeout=float(e.get("timeout", 60.0)),
        max_retries=int(e.get("max_retries", 4)),
    )
    return CachedEmbedder(client, e.get("cache_dir"))


def _vector_store(cfg: Config) -> VectorStore:
    v = cfg.vector
    api_key = os.environ.get(v["api_key_env"]) if v.get("api_key_env") else None
    return VectorStore(
        dim=int(cfg.embedding["dim"]),
        path=v.get("path"),
        url=v.get("url"),
        collection=v.get("collection", "yedai"),
        api_key=api_key,
    )


def _searcher(cfg: Config, with_vectors: bool = False) -> Searcher:
    dictionary = _dictionary(cfg)
    try:
        idx = Index.load(cfg.index_path)
        idx.check_signature(cfg.index_signature(dictionary.fingerprint()))
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]索引錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc

    vectors = None
    if with_vectors:
        store = _vector_store(cfg)
        # 有向量才接上。沒有就讓 D/E 明確地「不可用」——這比接上一個空的向量庫
        # 然後回傳零筆結果好得多：後者看起來像「稠密腿沒有用」。
        if store.has_vectors():
            vectors = VectorSearcher(store, _embedder(cfg))
        else:
            store.close()
    return Searcher(idx, cfg, dictionary, vectors=vectors)


def _render(result: ModeResult, show_legs: bool = False) -> Table:
    table = Table(title=f"模式 {result.mode}（候選 {result.candidates}）", show_lines=False)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("score", justify="right", width=8)
    if show_legs:
        table.add_column("lex", justify="right", width=6)
        table.add_column("ent", justify="right", width=6)
    table.add_column("concept_id", style="cyan", no_wrap=True)
    table.add_column("type", style="magenta", no_wrap=True)
    table.add_column("title")
    for hit in result.hits:
        row = [str(hit.rank), f"{hit.score:.4f}"]
        if show_legs:
            row += [f"{hit.lexical_score:.3f}", f"{hit.entity_score:.3f}"]
        row += [hit.concept_id, hit.type, hit.title]
        table.add_row(*row)
    if not result.hits:
        table.add_row(*(["—"] * (6 if show_legs else 4)))
    return table


# ---------------------------------------------------------------------------


@app.command()
def index(
    bundles: Path = typer.Argument(..., help="bundle 根目錄"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """解析 OKF bundle 並建立索引快取。"""
    cfg = _config(config)
    if not bundles.exists() or not bundles.is_dir():
        err.print(f"[red]找不到 bundle 根目錄：[/red] {bundles}")
        raise typer.Exit(2)

    dictionary = _dictionary(cfg)
    with console.status("解析與建索引中…"):
        idx = build_index(bundles, cfg, dictionary)
    path = idx.save(cfg.index_path)

    s = idx.stats
    table = Table(title="語料統計", show_header=False)
    table.add_column("項目", style="bold")
    table.add_column("值", justify="right")
    table.add_row("bundles", str(s.bundles))
    table.add_row("concepts", str(s.concepts))
    table.add_row("平均 concept 字元數", f"{s.avg_concept_chars:.0f}")
    table.add_row("平均 figures / concept", f"{s.avg_figures:.2f}")
    table.add_row("詞彙量（naive）", str(s.vocab_naive))
    table.add_row("詞彙量（protected）", str(s.vocab_protected))
    table.add_row("不重複實體", str(s.entities_total))
    table.add_row("  來自字典", str(s.entities_dict))
    table.add_row("  來自 regex fallback", str(s.entities_regex))
    table.add_row("懸空關聯", str(s.dangling_related))
    table.add_row("解析失敗", str(s.parse_skipped))
    table.add_row("解析警告", str(s.parse_warnings))
    console.print(table)

    if s.types:
        tt = Table(title="type 分佈")
        tt.add_column("type")
        tt.add_column("concepts", justify="right")
        for name, count in list(s.types.items())[:20]:
            tt.add_row(name, str(count))
        console.print(tt)

    if idx.skipped:
        err.print(f"\n[yellow]解析失敗 {len(idx.skipped)} 檔：[/yellow]")
        for line in idx.skipped[:20]:
            err.print(f"  - {line}")
        if len(idx.skipped) > 20:
            err.print(f"  … 另有 {len(idx.skipped) - 20} 筆")
    for line in idx.warnings[:20]:
        err.print(f"[yellow]警告：[/yellow] {line}")

    console.print(f"\n索引已寫入 [green]{path}[/green]")


@app.command()
def embed(
    bundles: Path = typer.Argument(..., help="bundle 根目錄（用於判定語料是否為合成）"),
    config: Optional[Path] = ConfigOpt,
    batch: int = typer.Option(64, "--batch", help="每次寫入向量庫的筆數"),
) -> None:
    """為每個 concept 產生向量並寫入向量庫（模式 D / E 的前置）。"""
    cfg = _config(config)
    _load_dotenv()
    base_url = cfg.embedding["base_url"]

    # 送出之前的最後一道閘。一旦送出就收不回來，所以預設是拒絕而不是警告。
    try:
        guard_corpus_leaves_process(
            bundles, base_url, bool(cfg.embedding.get("trusted_endpoint", False))
        )
    except CorpusLeakGuard as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    dictionary = _dictionary(cfg)
    try:
        idx = Index.load(cfg.index_path)
        idx.check_signature(cfg.index_signature(dictionary.fingerprint()))
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]索引錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc

    store = _vector_store(cfg)
    store.ensure_collection()
    embedder = _embedder(cfg)

    max_chars = int(cfg.embedding.get("max_chars", 6000))
    texts = [_embed_text(idx, meta, max_chars) for meta in idx.docs]
    console.print(
        f"{len(texts)} 個 concept → [cyan]{base_url}[/cyan]  "
        f"model=[cyan]{cfg.embedding['model']}[/cyan] dim={cfg.embedding['dim']}"
    )

    written = 0
    try:
        with console.status("嵌入中…") as status:
            for start in range(0, len(texts), batch):
                chunk = texts[start : start + batch]
                vectors = embedder.embed(chunk)
                store.upsert(
                    [
                        (idx.docs[start + i].concept_id, vec)
                        for i, vec in enumerate(vectors)
                    ]
                )
                written += len(chunk)
                status.update(f"嵌入中… {written}/{len(texts)}")
    except EmbeddingError as exc:
        err.print(f"[red]嵌入失敗：[/red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        store.close()

    console.print(
        f"已寫入 [green]{written}[/green] 個向量"
        f"（快取命中 {embedder.hits}／請求 {embedder.misses}）"
    )


def _embed_text(idx: Index, meta, max_chars: int) -> str:
    """一個 concept 一個向量：標題／描述／標籤 + 內文。

    內文必須進來——稠密腿的價值在於「用詞與文件不重疊時仍找得到」，
    只嵌標題等於把它降級成一個比較模糊的關鍵字檢索，然後得出「稠密沒有用」的結論。

    刻意**不分塊**：分塊會同時改變召回粒度與融合行為，兩個變因一起動就分不出是誰的功勞。
    等 D 與 E 的數字出來再決定值不值得。超長者截斷，並在此留下記號。
    """
    head = "\n".join(p for p in (meta.title, meta.description, " ".join(meta.tags or [])) if p)
    try:
        body = load_concept(idx, meta.concept_id).get("raw", "")
    except (ConceptNotFound, ConceptFileMissing, ConceptPathEscape):
        body = ""
    text = f"{head}\n\n{body}".strip()
    return text[:max_chars]


@app.command()
def search(
    query: str = typer.Argument(..., help="查詢字串"),
    mode: str = typer.Option("C", "--mode", "-m", help="檢索模式：A / B / C / D / E"),
    k: Optional[int] = typer.Option(None, "--top", "-k", help="回傳筆數"),
    config: Optional[Path] = ConfigOpt,
    log: bool = typer.Option(True, help="是否寫入查詢日誌"),
) -> None:
    """以單一模式查詢。"""
    cfg = _config(config)
    searcher = _searcher(cfg, with_vectors=True)
    try:
        result = searcher.search(query, mode, k)
    except (ValueError, ModeUnavailable) as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    console.print(_render(result, show_legs=result.mode == "C"))
    if log:
        from .search import SearchOutcome

        store = TelemetryStore.create(cfg)
        outcome = SearchOutcome(
            query=query,
            k=k or cfg.top_k,
            results={result.mode: result},
            entities=searcher.extract_query_entities(query),
        )
        qid = store.log_query(outcome, requested_mode=result.mode)
        console.print(f"[dim]query_id={qid}[/dim]")


@app.command()
def compare(
    query: Optional[str] = typer.Argument(None, help="查詢字串（與 --file 二擇一）"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="每行一個查詢的檔案"),
    k: Optional[int] = typer.Option(None, "--top", "-k", help="回傳筆數"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """對同一查詢並排執行 A / B / C 三模式，並顯示模式間重疊度。"""
    cfg = _config(config)
    if not query and not file:
        err.print("[red]請提供查詢字串或 --file[/red]")
        raise typer.Exit(2)

    queries: list[str] = []
    if query:
        queries.append(query)
    if file:
        if not file.exists():
            err.print(f"[red]找不到查詢檔：[/red] {file}")
            raise typer.Exit(2)
        # 必須濾掉 `#` 開頭：`gen-queries` 的檔頭記錄了組成與種子，
        # 把它當成查詢會讓一整批註解文字混進統計裡。
        queries += load_queries(file)

    searcher = _searcher(cfg, with_vectors=True)
    store = TelemetryStore.create(cfg)
    # 寫死配對會在模式增加時靜靜漏掉新的那幾組，而漏掉的正是新機制值不值得的依據。
    agg: dict[str, list[float]] = defaultdict(list)
    single = len(queries) == 1

    for q in queries:
        outcome = searcher.compare(q, k)
        store.log_query(outcome, requested_mode="compare")
        for ov in outcome.overlaps:
            agg[ov.pair].append(ov.jaccard)

        if single:
            if outcome.entities:
                console.print(
                    "查詢實體："
                    + "、".join(f"{e.canonical}[{e.type}/{e.source}]" for e in outcome.entities)
                )
            else:
                console.print("[dim]查詢中未偵測到實體[/dim]")
            for mode in MODES:
                console.print(_render(outcome.results[mode], show_legs=mode == "C"))

            ot = Table(title="模式間 top-k 重疊度")
            ot.add_column("pair")
            ot.add_column("jaccard", justify="right")
            ot.add_column("kendall tau", justify="right")
            ot.add_column("common", justify="right")
            for ov in outcome.overlaps:
                tau = "—" if ov.kendall_tau is None else f"{ov.kendall_tau:.3f}"
                ot.add_row(ov.pair, f"{ov.jaccard:.3f}", tau, str(ov.common))
            console.print(ot)

    if not single:
        st = Table(title=f"批次彙總（{len(queries)} 個查詢）")
        st.add_column("pair")
        st.add_column("平均 jaccard", justify="right")
        st.add_column("最小", justify="right")
        st.add_column("最大", justify="right")
        for pair, vals in agg.items():
            if not vals:
                continue
            st.add_row(pair, f"{sum(vals) / len(vals):.3f}", f"{min(vals):.3f}", f"{max(vals):.3f}")
        console.print(st)
        console.print(
            "\n[dim]jaccard 越接近 1 代表該兩個模式的 top-k 幾乎相同，"
            "亦即該干預沒有實際作用。[/dim]"
        )


@app.command()
def report(
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="輸出 JSON 路徑；省略則印到終端"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """產出去識別化統計報告（零語料內容，可安全分享）。"""
    cfg = _config(config)
    dictionary = _dictionary(cfg)
    try:
        idx = Index.load(cfg.index_path)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]索引錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc

    data = build_report(idx, TelemetryStore.create(cfg), cfg)
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(blob + "\n", encoding="utf-8")
        console.print(f"報告已寫入 [green]{out}[/green]（不含任何語料內容，可直接分享）")
    else:
        console.print_json(blob)


@app.command("gen-queries")
def gen_queries(
    n: int = typer.Option(40, "--count", "-n", help="產生幾條查詢"),
    out: Path = typer.Option(Path("queries.local.txt"), "--out", "-o", help="輸出路徑"),
    seed: int = typer.Option(7, "--seed", "-s", help="亂數種子"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """從真實語料取樣產生查詢清單（`mode_overlap` 的唯一前置條件）。"""
    cfg = _config(config)
    dictionary = _dictionary(cfg)
    try:
        idx = Index.load(cfg.index_path)
        idx.check_signature(cfg.index_signature(dictionary.fingerprint()))
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]索引錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc

    tok = Tokenizer(cfg.identifier_specs())
    qs = generate_queries(idx, dictionary, n, tok, seed=seed, mix=DEFAULT_MIX)
    out.write_text(render_queries(qs, seed, DEFAULT_MIX, cfg.index_path), encoding="utf-8")

    table = Table(title=f"查詢組成（{len(qs.queries)} 條）")
    table.add_column("組成")
    table.add_column("筆數", justify="right")
    for name, count in qs.composition.items():
        table.add_row(name, str(count))
    console.print(table)

    pool = Table(title="素材種類數")
    pool.add_column("來源")
    pool.add_column("種類", justify="right")
    for name, size in qs.pool_sizes.items():
        pool.add_row(name, str(size))
    console.print(pool)
    # 缺口要看得見。靜靜補到別組去會讓「模式 C 沒有用」這種結論建立在
    # 「根本沒有測到模式 C」之上。
    for name, why in qs.shortfalls.items():
        err.print(f"[yellow]⚠ {name}：[/yellow] {why}")

    console.print(f"\n已寫入 [green]{out}[/green]")
    console.print(
        "[dim]這份清單含真實識別碼，預設路徑已被 gitignore。\n"
        "它能回答「機制會不會改變結果」，不能回答「工程師是不是這樣查」。[/dim]"
    )
    console.print(f"\n接著跑：[cyan]yedai compare -f {out} -c {config or 'config.yaml'}[/cyan]")


@app.command("gen-synthetic")
def gen_synthetic(
    out: Path = typer.Argument(..., help="輸出目錄"),
    bundles: int = typer.Option(30, "--bundles", "-n", help="bundle 數量"),
    seed: int = typer.Option(42, "--seed", "-s", help="隨機種子"),
) -> None:
    """產生合成 OKF bundle（僅供驗證程式正確性，不得用於調參或推論效果）。"""
    from .synthetic import DISCLAIMER, generate

    with console.status("產生合成語料中…"):
        result = generate(out, n_bundles=bundles, seed=seed)
    console.print_json(json.dumps(result, ensure_ascii=False))
    err.print(f"\n[yellow]{DISCLAIMER}[/yellow]")


@app.command()
def mcp(config: Optional[Path] = ConfigOpt) -> None:
    """啟動 MCP server（stdio），供 claude-agent-sdk 等 agent 連接。"""
    from .mcp_server import main as mcp_main

    _config(config)  # 提早驗證設定，錯誤才不會變成 stdio 上的雜訊
    try:
        mcp_main(str(config) if config else None)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]MCP server 啟動失敗：[/red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="綁定位址"),
    port: int = typer.Option(8000, help="連接埠"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """啟動 HTTP API（互動式文件頁在 /docs）。"""
    import uvicorn

    _config(config)  # 提早驗證設定
    if config:
        os.environ["YEDAI_CONFIG"] = str(config)
    console.print(f"互動式 API 文件： [green]http://{host}:{port}/docs[/green]")
    uvicorn.run("yedai.api:app", host=host, port=port, log_level="info")


@app.command("check-formats")
def check_formats(config: Optional[Path] = ConfigOpt) -> None:
    """驗證識別碼樣式涵蓋得了真實形狀。

    樣本檔留在本機（真實識別碼屬敏感資料），只有涵蓋與否會被拿來把關。
    存在未涵蓋或部分涵蓋的樣本時以非零狀態碼結束，可直接接進 CI。
    """
    from .tokenizer import Tokenizer

    cfg = _config(config)
    try:
        samples = load_samples(cfg.identifier_samples_path)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]樣本檔錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc

    if not samples:
        err.print(
            "[yellow]未設定 identifier_samples_path。[/yellow]\n"
            "沒有樣本就沒有任何機制能發現「樣式對不上真實語料」——"
            "而那正是模式 B/C 失效時最難察覺的形式。\n"
            "參考 identifier-samples.example.yaml 建立一份本機樣本檔。"
        )
        raise typer.Exit(2)

    report = check_coverage(Tokenizer(cfg.identifier_specs()), samples)

    table = Table(title="識別碼格式涵蓋率")
    table.add_column("類型")
    table.add_column("樣本")
    table.add_column("判定")
    table.add_column("實際詞元")
    styles = {FULL: "green", INTACT: "cyan", PARTIAL: "red", NONE: "red"}
    labels = {FULL: "識別碼", INTACT: "完整詞元", PARTIAL: "咬錯", NONE: "碎裂"}
    for etype, results in report.by_type().items():
        for r in results:
            table.add_row(
                etype,
                r.sample,
                f"[{styles[r.verdict]}]{labels[r.verdict]}[/{styles[r.verdict]}]",
                "" if r.verdict == FULL else " ".join(r.tokens),
            )
    console.print(table)

    if report.types_without_samples:
        console.print(
            f"\n[yellow]無樣本的類型：[/yellow] {', '.join(report.types_without_samples)}\n"
            "這不是通過——是我們不知道這些類型的樣式有沒有效。"
        )

    if report.intact_only:
        types = sorted({r.type for r in report.intact_only})
        console.print(
            f"\n[cyan]{len(report.intact_only)} 個樣本沒有被圈成識別碼，但詞元完整[/cyan]"
            f"（{', '.join(types)}）。\n"
            "檢索不受損——模式 A 會把它們切碎，模式 B 不會，鑑別力的差異仍在。\n"
            "唯一的差別是它們不會進入實體空間，所以模式 C 看不到它們；"
            "若該類型有字典，字典的字面掃描會補上這一塊。"
        )

    if not report.ok:
        err.print(
            f"\n[red]{len(report.failures)} 個樣本有問題。[/red]\n"
            "「咬錯」是正則從中間比對進去、憑空產生一個錯的識別碼，比沒抓到更糟；\n"
            "「碎裂」則讓識別碼失去鑑別力，兩者都會讓模式 B 被低估——"
            "而低估的方向剛好導出「識別碼保護沒有用」這個相反的結論。"
        )
        raise typer.Exit(1)

    console.print(f"\n[green]{len(report.results)} 個樣本全部沒有被切碎。[/green]")


if __name__ == "__main__":
    app()
