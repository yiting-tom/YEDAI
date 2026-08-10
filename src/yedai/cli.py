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

from .config import Config, IndexSpec
from .embedding import EmbeddingError, build_embedder, load_dotenv
from .entities import EntityDictionary, EntitySourceError
from .formats import FULL, INTACT, NONE, PARTIAL, check_coverage, load_samples
from .fulltext import ConceptFileMissing, ConceptNotFound, ConceptPathEscape, load_concept
from .evalset import (
    EVALSET_CAVEATS,
    KINDS,
    dump as dump_evalset,
    evaluate as run_evaluation,
    generate as build_evalset,
    load as load_evalset,
)
from .index import Index, build_index_for_spec, load_index_for_spec
from .layers import IdOverlap, LayeredOutcome, LayeredSearcher
from .runtime import ENV_CONFIG
from .llm import CachedChat, HttpChatClient
from .queries import (
    DEFAULT_MIX,
    generate as generate_queries,
    load as load_queries,
    render as render_queries,
)
from .search import ModeResult, ModeUnavailable, Searcher, VectorSearcher
from .taxonomy import Taxonomy
from .telemetry import TelemetryStore, build_report
from .tokenizer import Tokenizer
from .vectors import CorpusLeakGuard, VectorBackend, VectorStore, guard_corpus_leaves_process

app = typer.Typer(add_completion=False, help="OKF bundle 關鍵字檢索 baseline harness（A/B/C 消融）")
console = Console()
err = Console(stderr=True)

ConfigOpt = typer.Option(None, "--config", "-c", help="設定檔路徑（YAML）")
IndexOpt = typer.Option(None, "--index", "-i", help="索引名稱；省略則涵蓋全部已宣告的索引")


def _config(path: Optional[Path]) -> Config:
    try:
        return Config.load(path)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]設定錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc


def _config_with_indexes(path: Optional[Path]) -> Config:
    """啟動長時間服務前的檢查：連索引宣告都一起驗。

    只驗 `Config.load` 是不夠的——空設定在 Config 層是合法的（斷詞、格式檢查
    等路徑不需要索引）。於是服務會照常啟動、照常印出 /docs 的網址，然後每一個
    端點都回 503。失敗要發生在啟動時，不是第一個請求時。

    解析順序必須與 `Runtime.load` 一致（明確參數 > 環境變數 > 內建預設值）。
    不一致的話，這道檢查會擋掉一個服務其實跑得起來的設定——那比不檢查更糟。
    """
    cfg = _config(path or os.environ.get(ENV_CONFIG) or None)
    try:
        cfg.index_specs()
    except ValueError as exc:
        err.print(f"[red]設定錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc
    return cfg


def _dictionary(cfg: Config) -> EntityDictionary:
    try:
        return EntityDictionary.from_config(cfg)
    except (FileNotFoundError, EntitySourceError) as exc:
        # 畸形的來源檔要當場停下來。載入一半的字典比沒有字典更糟——
        # 模式 C 會安靜地變差，而那看起來就像「字典沒有用」。
        err.print(f"[red]字典錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc


def _specs(cfg: Config) -> dict[str, IndexSpec]:
    try:
        return cfg.index_specs()
    except ValueError as exc:
        err.print(f"[red]設定錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc


def _spec(cfg: Config, name: str) -> IndexSpec:
    specs = _specs(cfg)
    if name not in specs:
        err.print(f"[red]未宣告的索引名稱 [/red]{name!r}；可用的有 {sorted(specs)}")
        raise typer.Exit(2)
    return specs[name]


def _selected(cfg: Config, name: Optional[str]) -> list[str]:
    """要處理哪些索引。指定名稱時只有它；否則全部，並依依賴順序。"""
    if name is not None:
        _spec(cfg, name)
        return [name]
    _specs(cfg)
    return cfg.index_build_order()


def _backend(cfg: Config) -> VectorBackend:
    """全部 collection 共用一個 client。

    本機檔案模式的 qdrant 對儲存資料夾持有獨佔鎖：每層各開一個 client，
    第二個有向量的層就會撞鎖，而錯誤訊息指向 qdrant、不指向設定。
    """
    v = cfg.vector
    api_key = os.environ.get(v["api_key_env"]) if v.get("api_key_env") else None
    return VectorBackend(path=v.get("path"), url=v.get("url"), api_key=api_key)


def _vector_store(
    cfg: Config, spec: IndexSpec, backend: Optional[VectorBackend] = None
) -> Optional[VectorStore]:
    """索引沒宣告 collection 就沒有稠密腿。回 None 而不是建一個空的——
    空向量庫會讓 D/E 回傳零筆，而那看起來像「稠密腿沒有用」。"""
    if not spec.collection:
        return None
    owned = backend or _backend(cfg)
    return owned.store(int(cfg.embedding["dim"]), spec.collection)


def _index(cfg: Config, name: str) -> Index:
    dictionary = _dictionary(cfg)
    spec = _spec(cfg, name)
    try:
        return load_index_for_spec(spec, cfg, dictionary)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]索引錯誤：[/red] {exc}")
        raise typer.Exit(2) from exc


def _searcher(
    cfg: Config,
    name: str,
    with_vectors: bool = False,
    backend: Optional[VectorBackend] = None,
) -> Searcher:
    dictionary = _dictionary(cfg)
    spec = _spec(cfg, name)
    idx = _index(cfg, name)

    vectors = None
    if with_vectors:
        store = _vector_store(cfg, spec, backend)
        # 有向量才接上。沒有就讓 D/E 明確地「不可用」——這比接上一個空的向量庫
        # 然後回傳零筆結果好得多：後者看起來像「稠密腿沒有用」。
        if store is not None and store.has_vectors():
            vectors = VectorSearcher(store, build_embedder(cfg))
    return LayeredSearcher.searcher_for(spec, idx, cfg, dictionary, vectors)


def _layered(cfg: Config, with_vectors: bool = False) -> LayeredSearcher:
    """全部索引各自建立綁定的 `Searcher`，交給分層協調層。

    向量 backend 只開一次並由全部層共用——見 `_backend`。
    """
    names = _selected(cfg, None)
    backend = _backend(cfg) if with_vectors and any(_spec(cfg, n).collection for n in names) else None
    searchers = {name: _searcher(cfg, name, with_vectors, backend) for name in names}
    layered = LayeredSearcher(searchers, cfg)
    _warn_overlap(layered)
    return layered


def _warn_overlap(layered: LayeredSearcher) -> None:
    """跨層 concept_id 相撞是設定或語料的錯，而且它的症狀全部是靜默的。"""
    overlap = layered.id_overlap
    if not overlap:
        return
    err.print(
        f"[yellow]警告：{overlap.total} 個 concept_id 同時存在於多個索引"
        f"（{', '.join(sorted(overlap.pairs))}）。各層語料應互斥；"
        f"重疊會讓取全文靜默取第一層、跨層融合對同一份文件重複加權。[/yellow]"
    )


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
    name: Optional[str] = IndexOpt,
    config: Optional[Path] = ConfigOpt,
) -> None:
    """解析 OKF bundle 並建立索引快取。

    省略 `-i` 時依 `depends_on` 的拓撲順序建構全部索引。順序不是裝飾：上游是
    下游的實體字典來源，反過來建會讓下游用到舊字典，而那不會報錯。
    """
    cfg = _config(config)
    dictionary = _dictionary(cfg)
    names = _selected(cfg, name)
    specs = _specs(cfg)

    for target in names:
        spec = specs[target]
        with console.status(f"解析與建索引中… [{target}]"):
            try:
                idx = build_index_for_spec(spec, cfg, dictionary)
            except FileNotFoundError as exc:
                err.print(f"[red]索引 {target!r}：[/red] {exc}")
                raise typer.Exit(2) from exc
        _print_index_stats(target, idx)
        console.print(f"索引 [cyan]{target}[/cyan] 已寫入 [green]{spec.path}[/green]\n")

    if len(names) > 1:
        console.print(f"[dim]建構順序：{' → '.join(names)}（依 depends_on）[/dim]")


def _print_index_stats(name: str, idx: Index) -> None:
    s = idx.stats
    table = Table(title=f"語料統計 — 索引 {name}", show_header=False)
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
        tt = Table(title=f"type 分佈 — 索引 {name}")
        tt.add_column("type")
        tt.add_column("concepts", justify="right")
        for tname, count in list(s.types.items())[:20]:
            tt.add_row(tname, str(count))
        console.print(tt)

    if idx.skipped:
        err.print(f"\n[yellow]索引 {name}：解析失敗 {len(idx.skipped)} 檔：[/yellow]")
        for line in idx.skipped[:20]:
            err.print(f"  - {line}")
        if len(idx.skipped) > 20:
            err.print(f"  … 另有 {len(idx.skipped) - 20} 筆")
    for line in idx.warnings[:20]:
        err.print(f"[yellow]索引 {name} 警告：[/yellow] {line}")


@app.command()
def embed(
    name: Optional[str] = IndexOpt,
    config: Optional[Path] = ConfigOpt,
    batch: int = typer.Option(64, "--batch", help="每次寫入向量庫的筆數"),
) -> None:
    """為每個 concept 產生向量並寫入向量庫（模式 D / E 的前置）。

    省略 `-i` 時對所有宣告了 collection 的索引執行。每個索引寫進自己的 collection：
    不同層的稠密腿價值不同，分開才能分開決定要不要付這筆 embedding 成本。
    """
    cfg = _config(config)
    load_dotenv()
    base_url = cfg.embedding["base_url"]
    specs = _specs(cfg)
    targets = [n for n in _selected(cfg, name) if specs[n].collection]

    if not targets:
        scope = f"索引 {name!r}" if name else "任何索引"
        err.print(f"[red]{scope} 沒有宣告 collection，沒有可寫入的向量庫。[/red]")
        raise typer.Exit(2)

    embedder = build_embedder(cfg)
    # 全部 collection 共用一個 client；逐層各開一個會在第二層撞上本機 qdrant 的獨佔鎖。
    backend = _backend(cfg)
    for target in targets:
        spec = specs[target]
        # 送出之前的最後一道閘。一旦送出就收不回來，所以預設是拒絕而不是警告。
        # 每個索引各自判定——一層是合成語料不代表另一層也是。
        try:
            guard_corpus_leaves_process(
                spec.source, base_url, bool(cfg.embedding.get("trusted_endpoint", False))
            )
        except CorpusLeakGuard as exc:
            err.print(f"[red]索引 {target!r}：{exc}[/red]")
            raise typer.Exit(2) from exc

        idx = _index(cfg, target)
        store = _vector_store(cfg, spec, backend)
        assert store is not None  # targets 已篩選過 collection
        store.ensure_collection()

        max_chars = int(cfg.embedding.get("max_chars", 6000))
        texts = [_embed_text(idx, meta, max_chars) for meta in idx.docs]
        console.print(
            f"[cyan]{target}[/cyan]：{len(texts)} 個 concept → [cyan]{base_url}[/cyan]  "
            f"model=[cyan]{cfg.embedding['model']}[/cyan] dim={cfg.embedding['dim']} "
            f"collection=[cyan]{spec.collection}[/cyan]"
        )

        written = 0
        try:
            with console.status(f"嵌入中… [{target}]") as status:
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
                    status.update(f"嵌入中… [{target}] {written}/{len(texts)}")
        except EmbeddingError as exc:
            backend.close()
            err.print(f"[red]索引 {target!r} 嵌入失敗：[/red] {exc}")
            raise typer.Exit(1) from exc

        console.print(f"  已寫入 [green]{written}[/green] 個向量")

    backend.close()
    console.print(f"[dim]快取命中 {embedder.hits}／請求 {embedder.misses}[/dim]")


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
    name: Optional[str] = IndexOpt,
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help="檢索模式：A / B / C / D / E；省略則用各層宣告的預設"),
    k: Optional[int] = typer.Option(None, "--top", "-k", help="回傳筆數；省略則用各層宣告的深度"),
    fuse: bool = typer.Option(False, "--fuse", help="額外附上跨索引 RRF 融合清單"),
    config: Optional[Path] = ConfigOpt,
    log: bool = typer.Option(True, help="是否寫入查詢日誌"),
) -> None:
    """查詢。省略 `-i` 時分層檢索全部索引。

    分層而不是混成一份排序：RRF 融合的前提是兩份排名在回答同一個問題，跨模式
    滿足，跨索引不滿足。`--fuse` 保留了融合，供對照，但它不是預設。
    """
    cfg = _config(config)
    layered = _layered(cfg, with_vectors=True)
    try:
        outcome = layered.search(query, index=name, mode=mode, k=k, fuse=fuse)
    except (ValueError, ModeUnavailable) as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    _render_layered(outcome)
    if log:
        store = TelemetryStore.create(cfg)
        qid = store.log_layered(outcome, requested_index=name)
        console.print(f"[dim]query_id={qid}[/dim]")


def _render_layered(outcome: LayeredOutcome) -> None:
    """每層一段。空層仍然印出來——層的缺席本身是訊號，省略會讓它與
    「排在回傳筆數之外」不可區分。"""
    for layer in outcome.layers:
        title = f"索引 {layer.index} · 模式 {layer.mode}（候選 {layer.candidates}）"
        if layer.prepared_query != outcome.query:
            title += f" · 查詢經前處理 → {layer.prepared_query!r}"
        table = Table(title=title, show_lines=False)
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("score", justify="right", width=8)
        table.add_column("concept_id", style="cyan", no_wrap=True)
        table.add_column("type", style="magenta", no_wrap=True)
        table.add_column("title")
        for hit in layer.hits:
            table.add_row(str(hit.rank), f"{hit.score:.4f}", hit.concept_id, hit.type, hit.title)
        if layer.empty:
            table.add_row("—", "—", "[dim]（這一層沒有命中）[/dim]", "—", "—")
        console.print(table)

    if outcome.fused is None:
        return
    ft = Table(title="跨索引 RRF 融合（平權）")
    ft.add_column("#", justify="right", style="dim", width=3)
    ft.add_column("score", justify="right", width=8)
    ft.add_column("來源索引", style="green", no_wrap=True)
    ft.add_column("層內名次", justify="right", width=8)
    ft.add_column("concept_id", style="cyan", no_wrap=True)
    ft.add_column("title")
    for fh in outcome.fused:
        ft.add_row(
            str(fh.rank),
            f"{fh.score:.4f}",
            fh.index,
            str(fh.source_rank),
            fh.hit.concept_id,
            fh.hit.title,
        )
    if not outcome.fused:
        ft.add_row(*(["—"] * 6))
    console.print(ft)


def _single_index(cfg: Config, name: Optional[str], why: str) -> str:
    """模式消融只在單一索引內成立——跨索引比模式是在比兩件不同的事。"""
    if name is not None:
        _spec(cfg, name)
        return name
    names = _selected(cfg, None)
    if len(names) == 1:
        return names[0]
    err.print(f"[red]有 {len(names)} 個索引（{sorted(names)}），{why} 請以 -i 指定其中一個。[/red]")
    raise typer.Exit(2)


@app.command()
def compare(
    query: Optional[str] = typer.Argument(None, help="查詢字串（與 --file 二擇一）"),
    name: Optional[str] = IndexOpt,
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="每行一個查詢的檔案"),
    k: Optional[int] = typer.Option(None, "--top", "-k", help="回傳筆數"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """對同一查詢並排執行各可用模式，並顯示模式間重疊度。

    模式比較固定在**單一索引內**進行：跨索引比模式是在比兩件不同的事，
    重疊度會變成「這兩層語料有多像」而不是「這個干預有沒有作用」。
    """
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

    target = _single_index(cfg, name, "模式比較只在單一索引內成立，")
    searcher = _searcher(cfg, target, with_vectors=True)
    store = TelemetryStore.create(cfg)
    console.print(f"[dim]索引：{target}[/dim]")
    # 寫死配對會在模式增加時靜靜漏掉新的那幾組，而漏掉的正是新機制值不值得的依據。
    agg: dict[str, list[float]] = defaultdict(list)
    single = len(queries) == 1

    for q in queries:
        outcome = searcher.compare(q, k)
        store.log_query(outcome, requested_mode="compare", index=target)
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
            for mode in searcher.available_modes:
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
    evaluation: Optional[Path] = typer.Option(
        None, "--evaluation", "-e", help="`yedai evaluate -o` 的輸出，併入報告"
    ),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """產出去識別化統計報告（零語料內容，可安全分享）。"""
    cfg = _config(config)
    specs = _specs(cfg)
    # 語料統計依索引拆解。不同層的規模可能相差數個數量級，只給彙總會把它們平均掉。
    indexes: dict[str, Index] = {}
    for target in cfg.index_build_order():
        try:
            indexes[target] = Index.load(specs[target].path, expect_name=target)
        except (FileNotFoundError, ValueError) as exc:
            err.print(f"[red]索引 {target!r} 錯誤：[/red] {exc}")
            raise typer.Exit(2) from exc

    evals = json.loads(evaluation.read_text(encoding="utf-8")) if evaluation else None
    data = build_report(
        indexes,
        TelemetryStore.create(cfg),
        cfg,
        evaluation=evals,
        taxonomy=Taxonomy.from_config(cfg),
        # 與 HTTP 的 /v1/report 走同一個量法——同一份報告從兩個入口產出的數字
        # 不一樣，比缺一個欄位更難察覺。
        id_overlap=IdOverlap.measure(indexes).to_dict(),
    )
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(blob + "\n", encoding="utf-8")
        console.print(f"報告已寫入 [green]{out}[/green]（不含任何語料內容，可直接分享）")
    else:
        console.print_json(blob)


@app.command("gen-evalset")
def gen_evalset(
    name: Optional[str] = IndexOpt,
    n: int = typer.Option(30, "--count", "-n", help="取樣幾個 concept"),
    out: Path = typer.Option(Path("evalset.local.jsonl"), "--out", "-o", help="輸出路徑"),
    seed: int = typer.Option(7, "--seed", "-s", help="取樣種子"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """讓 LLM 讀 concept 產出「查詢 + 標準答案」，解鎖 recall@k 與 MRR。

    評估集綁定單一索引：不同層的檢索性質不同，混在一份評估集裡量出來的數字
    無法歸因到任何一層。
    """
    cfg = _config(config)
    load_dotenv()
    base_url = cfg.llm["base_url"]
    target = _single_index(cfg, name, "評估集綁定單一索引，")
    spec = _spec(cfg, target)

    # 與 `embed` 同一道閘。信任宣告各自獨立——embedding 可信不代表 LLM 端點可信。
    try:
        guard_corpus_leaves_process(
            spec.source, base_url, bool(cfg.llm.get("trusted_endpoint", False)), config_key="llm"
        )
    except CorpusLeakGuard as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    idx = _index(cfg, target)
    chat = CachedChat(
        HttpChatClient(
            base_url=base_url,
            model=cfg.llm["model"],
            api_key_env=cfg.llm["api_key_env"],
            temperature=float(cfg.llm.get("temperature", 0.0)),
            timeout=float(cfg.llm.get("timeout", 120.0)),
            max_retries=int(cfg.llm.get("max_retries", 4)),
        ),
        cfg.llm.get("cache_dir"),
    )

    def text_of(meta):
        return _embed_text(idx, meta, int(cfg.llm.get("max_chars", 4000)))

    console.print(f"取樣 {n} 個 concept → [cyan]{base_url}[/cyan] model=[cyan]{cfg.llm['model']}[/cyan]")
    with console.status("產生評估集…"):
        es = build_evalset(idx, chat, n, text_of, seed=seed)
    dump_evalset(es, out)

    console.print(
        f"{len(es.items)} 條查詢（取樣 {es.sampled} 篇，失敗 {es.failed} 篇；"
        f"快取命中 {chat.hits}／請求 {chat.misses}）"
    )
    if es.failed:
        # 失敗數要看得見：靜靜跳過會讓評估集悄悄偏向「LLM 剛好答得出來的那些文件」。
        err.print(f"[yellow]⚠ {es.failed} 篇回應無法解析，已跳過——評估集因此略偏。[/yellow]")
    for line in EVALSET_CAVEATS:
        console.print(f"[dim]• {line}[/dim]")
    console.print(f"\n已寫入 [green]{out}[/green]（含真實查詢，路徑已 gitignore）")
    console.print(f"接著跑：[cyan]yedai evaluate -f {out} -c {config or 'config.yaml'}[/cyan]")


@app.command()
def evaluate(
    name: Optional[str] = IndexOpt,
    file: Path = typer.Option(Path("evalset.local.jsonl"), "--file", "-f", help="評估集路徑"),
    k: int = typer.Option(10, "--top", "-k", help="計算 recall@k / MRR 的深度"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="輸出 JSON 路徑"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """對每個可用模式算 recall@k 與 MRR，並依查詢種類拆解。"""
    cfg = _config(config)
    if not file.exists():
        err.print(f"[red]找不到評估集：[/red] {file} — 先跑 `yedai gen-evalset`")
        raise typer.Exit(2)

    es = load_evalset(file)
    target = _single_index(cfg, name, "評估綁定單一索引，")
    console.print(f"[dim]索引：{target}[/dim]")
    searcher = _searcher(cfg, target, with_vectors=True)
    with console.status(f"評估 {len(es.items)} 條查詢 × {len(searcher.available_modes)} 個模式…"):
        result = run_evaluation(es, searcher, k=k)

    table = Table(title=f"recall@{k} / MRR（標籤只涵蓋單一相關文件，故為下界）")
    table.add_column("模式")
    table.add_column(f"recall@{k}", justify="right")
    table.add_column("MRR", justify="right")
    for kind in KINDS:
        table.add_column(f"{kind} recall", justify="right")
    for mode, m in result["overall"].items():
        row = [mode, f"{m['recall_at_k']:.3f}", f"{m['mrr']:.3f}"]
        for kind in KINDS:
            v = result["by_kind"][mode][kind]["recall_at_k"]
            row.append("—" if v is None else f"{v:.3f}")
        table.add_row(*row)
    console.print(table)

    for line in EVALSET_CAVEATS:
        console.print(f"[dim]• {line}[/dim]")

    if out:
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"\n已寫入 [green]{out}[/green]")


@app.command("gen-queries")
def gen_queries(
    name: Optional[str] = IndexOpt,
    n: int = typer.Option(40, "--count", "-n", help="產生幾條查詢"),
    out: Path = typer.Option(Path("queries.local.txt"), "--out", "-o", help="輸出路徑"),
    seed: int = typer.Option(7, "--seed", "-s", help="亂數種子"),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """從真實語料取樣產生查詢清單（`mode_overlap` 的唯一前置條件）。"""
    cfg = _config(config)
    dictionary = _dictionary(cfg)
    target = _single_index(cfg, name, "查詢取自單一索引的語料，")
    spec = _spec(cfg, target)
    idx = _index(cfg, target)

    tok = Tokenizer(cfg.identifier_specs())
    qs = generate_queries(idx, dictionary, n, tok, seed=seed, mix=DEFAULT_MIX)
    out.write_text(render_queries(qs, seed, DEFAULT_MIX, spec.path), encoding="utf-8")

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

    # 索引宣告也一起驗——錯誤才不會變成 stdio 上的雜訊，或每個工具呼叫的 503
    _config_with_indexes(config)
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

    # 索引宣告在這裡就要驗。少了它，服務會啟動、印出 /docs 的網址，
    # 然後每一個端點都 503——而錯誤只有在第一個請求打進來時才看得到。
    cfg = _config_with_indexes(config)
    if config:
        os.environ["YEDAI_CONFIG"] = str(config)
    console.print(f"索引：[cyan]{', '.join(cfg.index_build_order())}[/cyan]")
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
