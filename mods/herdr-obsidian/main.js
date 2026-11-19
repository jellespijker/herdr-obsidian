// Native Herdr-App GPUI Obsidian Vault mod for herdr-obsidian.
// Designed with Herdr's native visual language: single-bar chrome, editorial reading flow,
// restrained dark-mode architectural palette, and SVG-backed 2D Graph & Canvas views.
import { View, div, svg, image } from "gpui-kit";
import {
  v_flex,
  h_flex,
  Input,
  InputState,
  Editor,
  EditorState,
  TextView,
} from "gpui-base";
import {
  spaces,
  panes,
  focused,
  exec,
  run,
  theme,
  settings,
  props,
  home,
  appHome,
  checking,
  shared,
  watchFolder,
  nextCommand,
  notify,
  openOverlay,
  closeOverlay,
} from "herdr";
import * as fs from "fs/promises";

const B64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const B64_LOOKUP = new Uint8Array(256);
for (let i = 0; i < B64_CHARS.length; i++) B64_LOOKUP[B64_CHARS.charCodeAt(i)] = i;

function decodeBase64(b64) {
  const clean = String(b64 || "").replace(/[\r\n\s]/g, "");
  const len = clean.length;
  if (!len) return new Uint8Array(0);
  const pad = clean.endsWith("==") ? 2 : clean.endsWith("=") ? 1 : 0;
  const out = new Uint8Array(((len * 3) >> 2) - pad);
  let p = 0;
  for (let i = 0; i < len; i += 4) {
    const a = B64_LOOKUP[clean.charCodeAt(i)];
    const b = B64_LOOKUP[clean.charCodeAt(i + 1)];
    const c = B64_LOOKUP[clean.charCodeAt(i + 2)];
    const d = B64_LOOKUP[clean.charCodeAt(i + 3)];
    const triple = (a << 18) | (b << 12) | (c << 6) | d;
    if (p < out.length) out[p++] = (triple >> 16) & 0xff;
    if (p < out.length) out[p++] = (triple >> 8) & 0xff;
    if (p < out.length) out[p++] = triple & 0xff;
  }
  return out;
}

const VIEWS = [
  { id: "note", label: "Document" },
  { id: "treemap", label: "DiskTree" },
  { id: "graph", label: "Graph" },
  { id: "canvas", label: "Canvas" },
  { id: "ticket", label: "Ticket" },
];

const CANVAS_SURFACE_MAP = {
  "1": { border: "#6e3438", fill: "#26171a", accent: "#d46a6a" },
  "2": { border: "#6e462b", fill: "#261c16", accent: "#d48852" },
  "3": { border: "#665326", fill: "#252016", accent: "#c9a24b" },
  "4": { border: "#285943", fill: "#15251f", accent: "#4ea87d" },
  "5": { border: "#265563", fill: "#152329", accent: "#489fb5" },
  "6": { border: "#49366e", fill: "#1f192b", accent: "#916dd5" },
};

function levelTint(level, t) {
  if (level === 0) return "#c95b78";
  if (level === 1) return "#5882c9";
  if (level === 2) return "#46a377";
  if (level === 3) return "#8f6bc9";
  return t.muted;
}

function calloutTone(kind, t) {
  const k = String(kind || "note").toLowerCase();
  if (k === "important" || k === "abstract" || k === "summary") return "#8f6bc9";
  if (k === "tip" || k === "hint" || k === "success" || k === "check") return t.done || "#46a377";
  if (k === "warning" || k === "attention" || k === "question") return t.working || "#c49644";
  if (k === "caution" || k === "danger" || k === "error" || k === "bug") return t.blocked || "#d46a6a";
  return t.accent || "#5882c9";
}

function ghostBtn(id, label, t, opts = {}) {
  const { active, primary, onClick } = opts;
  const stop = (_e, cx) => cx.stop_propagation();
  return div()
    .id(id)
    .h(26)
    .px(8)
    .flex_none()
    .flex()
    .items_center()
    .justify_center()
    .rounded(5)
    .cursor_pointer()
    .text_size(11.5)
    .when(Boolean(primary), (el) =>
      el.bg(t.accent).text_color(t.solid_foreground || "#ffffff").font_medium()
    )
    .when(!primary && Boolean(active), (el) =>
      el.bg(t.selected).text_color(t.foreground).font_medium()
    )
    .when(!primary && !active, (el) => el.text_color(t.muted))
    .hover((s) =>
      s
        .bg(primary ? t.accent : t.hover)
        .text_color(primary ? t.solid_foreground || "#ffffff" : t.foreground)
    )
    .on_mouse_down("left", stop)
    .when(Boolean(onClick), (el) => el.on_click(onClick))
    .child(String(label ?? ""));
}

function resolveWorkspaceTarget(lastTarget) {
  const p = props() || {};
  const allSpaces = spaces() || [];
  const allPanes = panes() || [];
  const f = focused() || {};
  const activeSpace = allSpaces.find((s) => s.active) || allSpaces[0] || null;
  const spaceTabIds = new Set((activeSpace?.tabs || []).map((tb) => tb.id));
  const spacePanes = allPanes.filter((pn) => spaceTabIds.has(pn.tab));
  const focusedInSpace = Boolean(activeSpace && f?.space === activeSpace.id);
  const activeTab =
    (focusedInSpace && f?.tab && spaceTabIds.has(f.tab) ? f.tab : null) ||
    activeSpace?.tabs?.find((tb) => tb.active)?.id ||
    null;
  const focusedTermPane =
    focusedInSpace && f?.pane
      ? spacePanes.find((pn) => pn.pane === f.pane && pn.terminal)
      : null;
  const activeTabPanes = activeTab
    ? spacePanes.filter((pn) => pn.tab === activeTab && pn.terminal && pn.cwd)
    : [];
  const tabTermPane =
    activeTabPanes.find(
      (pn) =>
        !/^\/home\/[^/]+\/?$/.test(pn.cwd) && !/^\/Users\/[^/]+\/?$/.test(pn.cwd)
    ) ||
    activeTabPanes[0] ||
    null;
  const spaceTermPaneWithCwd =
    spacePanes.find(
      (pn) =>
        pn.terminal &&
        pn.cwd &&
        !/^\/home\/[^/]+\/?$/.test(pn.cwd) &&
        !/^\/Users\/[^/]+\/?$/.test(pn.cwd)
    ) ||
    spacePanes.find((pn) => pn.terminal && pn.cwd) ||
    null;
  const focusedInSpaceCwd = focusedInSpace ? f.cwd : null;
  const focusedInSpaceTerm = focusedInSpace ? f.terminal : null;

  const on =
    p.on ||
    p.machine ||
    activeSpace?.machine ||
    (f?.pane === null && focusedInSpaceTerm?.includes("/")
      ? focusedInSpaceTerm.split("/")[0]
      : null) ||
    null;

  const sameSpaceLastCwd =
    lastTarget && lastTarget.spaceId === activeSpace?.id ? lastTarget.cwd : null;

  const cwd =
    p.cwd ||
    p.folder ||
    focusedTermPane?.cwd ||
    tabTermPane?.cwd ||
    focusedInSpaceCwd ||
    spaceTermPaneWithCwd?.cwd ||
    (activeSpace?.name === "~" ? home() : activeSpace?.folder) ||
    sameSpaceLastCwd ||
    home() ||
    null;

  const sameSpaceLastPane =
    lastTarget && lastTarget.spaceId === activeSpace?.id ? lastTarget.pane : null;

  const rawPane =
    focusedTermPane?.terminal ||
    tabTermPane?.terminal ||
    focusedInSpaceTerm ||
    spaceTermPaneWithCwd?.terminal ||
    sameSpaceLastPane ||
    null;
  const pane = rawPane && String(rawPane).includes("/") ? String(rawPane).split("/")[1] : rawPane;

  return {
    cwd,
    on: on === "local" ? null : on,
    pane,
    spaceId: activeSpace?.id || null,
    spaceName: activeSpace?.name || "Workspace",
  };
}

export default class ObsidianVault extends View {
  init(_props, cx) {
    this.handle = cx.focus_handle();
    this.size = { width: 860, height: 680 };
    this.lastTarget = null;
    this.lastTargetKey = "";
    this.lastLocalCwd = null;
    this.state = null;
    this.loading = false;
    this.loadingTargetKey = "";
    this.refreshSeq = 0;
    this.pendingRefresh = null;
    this.error = null;

    const p = props() || {};
    this.isLightbox = Boolean(p.lightbox);
    if (this.isLightbox) {
      this.lightbox = { ...p.lightbox };
      this.lightboxKind = p.lightboxKind || "window";
      this.lbZoom = 1.0;
      this.lbPanX = 0;
      this.lbPanY = 0;
      this.lbDrag = null;
      this.lbShowSource = false;
      this.lbReady = false;
      if (checking()) return;
      this.ensureLightboxAsset(cx);
      cx.timer.after(40, () => this.handle.focus());
      return;
    }

    this.viewMode = p.view || "note";
    this.sidebarOpen = true;
    this.sidebarTab = "mocs"; // "mocs" | "tree" | "search"
    this.inspectorOpen = false; // Default closed so Document & Graph have full width
    this.followSync = true;
    this.editMode = false;
    this.typing = false;

    this.activeNotePath = p.note || p.file || null;
    this.activeTicket = p.ticket || null;
    this.history = [];
    this.historyIndex = -1;
    this.openFolders = new Set(["00-Map-Of-Content (MOC)", "01-Product-Process-Architecture"]);

    this.searchQuery = "";
    this.tagFilter = null;
    this.levelFilter = null;
    this.categoryFilter = null;
    this.treemapMetric = "bytes";
    this.treemapZoomFolder = "";
    this.hoveredTreemapCell = null;
    this.activeCanvasPath = p.canvas || null;
    this.graphMode = "local";

    this.panX = 0;
    this.panY = 0;
    this.zoom = 0.78;
    this.drag = null;

    this.lastSpoolSeq = 0;
    this.lastNavSeq = 0;
    this.watchedSpool = null;
    this.watchedVault = null;
    this.cachedAssets = new Set();
    this.diagramDims = new Map();
    this.diagramShowSource = new Set();
    this.renderingDiagrams = new Set();
    this.editorState = null;
    this.editorNotePath = null;

    this.searchInput = InputState.new({
      placeholder: "Filter vault… (/)",
      value: "",
    });
    this.searchInput.on("focus", (_ev, cx) => {
      this.typing = true;
      cx.notify();
    });
    this.searchInput.on("blur", (_ev, cx) => {
      this.typing = false;
      cx.notify();
    });
    this.searchInput.on("change", (_ev, cx) => {
      const val = (this.searchInput.value() || "").trim();
      this.searchQuery = val;
      if (val) {
        this.sidebarOpen = true;
        this.sidebarTab = "search";
      }
      this.refresh(cx);
    });
    this.searchInput.on("submit", (_ev, cx) => {
      const hits = this.state?.search_results || [];
      if (hits.length > 0) {
        this.openNote(hits[0].relpath, cx, { pushHistory: true });
      }
    });

    if (checking()) return;

    this.consumeSharedNav();

    cx.spawn(async (cx) => {
      for (;;) {
        const cmd = await nextCommand().catch(() => null);
        if (!cmd) break;
        if (cmd === "focus") {
          this.handle.focus();
          cx.notify();
        } else if (cmd === "refresh") {
          this.followSync = true;
          this.refresh(cx, { forceSync: true });
        } else if (cmd.startsWith("view-")) {
          const requestedView = cmd.slice("view-".length);
          if (VIEWS.some((v) => v.id === requestedView)) {
            this.viewMode = requestedView;
          }
          this.followSync = true;
          this.refresh(cx, { forceSync: true });
          cx.notify();
        } else if (cmd === "search") {
          this.searchInput.focus();
          cx.notify();
        }
      }
    });

    this.refresh(cx);
    cx.timer.every(4000, (cx) => this.refresh(cx, { background: true }));
  }

  consumeSharedNav() {
    const nav = shared("obsidian.nav");
    if (!nav || typeof nav !== "object") return false;
    const seq = Number(nav.seq || 0);
    if (!seq || seq <= this.lastNavSeq) return false;
    this.lastNavSeq = seq;
    this.followSync = true;
    if (nav.view && VIEWS.some((v) => v.id === nav.view)) {
      this.viewMode = nav.view;
    }
    if (nav.ticket) {
      this.activeTicket = String(nav.ticket);
    }
    if (nav.target) {
      const tgt = String(nav.target);
      if (tgt.endsWith(".canvas")) {
        this.activeCanvasPath = tgt;
      } else if (nav.view !== "ticket") {
        this.activeNotePath = tgt;
      }
    }
    if (nav.cwd && !nav.on) {
      this.lastLocalCwd = String(nav.cwd);
    }
    return true;
  }

  close(_cx) {
    if (this.editorState) {
      this.editorState.release();
      this.editorState = null;
    }
    this.searchInput?.release();
  }

  watchDirectory(dirPath, slotName, cx) {
    if (!dirPath || this.lastTarget?.on || this[slotName] === dirPath) return;
    this[slotName] = dirPath;
    cx.spawn(async (cx) => {
      try {
        while (this[slotName] === dirPath && !this.lastTarget?.on) {
          await watchFolder(dirPath);
          this.refresh(cx, { background: true });
        }
      } catch {
        if (this[slotName] === dirPath) this[slotName] = null;
      }
    });
  }

  async ensureAllAssets(data, target, cx) {
    const cacheDir = `${appHome()}/data/obsidian-cache`;
    await fs.mkdir(cacheDir, { recursive: true }).catch(() => {});
    let updated = false;

    // 1. Write inline base64 SVGs generated for Graph and Canvas underlays
    for (const overlay of [data?.graph, data?.canvas]) {
      const cName = overlay?.svg_cache_name;
      const b64 = overlay?.svg_b64;
      if (cName && b64 && !this.cachedAssets.has(cName)) {
        const dest = `${cacheDir}/${cName}`;
        try {
          if (!(await fs.exists(dest).catch(() => false))) {
            await fs.writeFile(dest, decodeBase64(b64));
          }
          this.cachedAssets.add(cName);
          updated = true;
        } catch {}
      }
    }

    // 2. Fetch embedded note figures (SVG/PNG) and inline Mermaid/D2/PlantUML diagrams
    const blocks = data?.active_note?.blocks || [];
    const noteRel = data?.active_note?.relpath || "";
    for (const blk of blocks) {
      if (blk.type === "image" && blk.cache_name && blk.relpath) {
        if (this.cachedAssets.has(blk.cache_name)) continue;
        const localFile = `${cacheDir}/${blk.cache_name}`;
        if (await fs.exists(localFile).catch(() => false)) {
          this.cachedAssets.add(blk.cache_name);
          continue;
        }
        try {
          const res = await exec("herdr-obsidian", ["app-artifact", blk.relpath], {
            cwd: target.cwd,
            on: target.on,
          });
          if (res.code === 0 && res.stdout) {
            const parsed = JSON.parse(res.stdout);
            if (parsed.ok && parsed.b64) {
              await fs.writeFile(localFile, decodeBase64(parsed.b64));
              this.cachedAssets.add(blk.cache_name);
              updated = true;
            }
          }
        } catch {}
      } else if (blk.type === "diagram" && blk.cache_name) {
        if (blk.width && blk.height && blk.rendered) {
          this.diagramDims.set(blk.cache_name, { width: blk.width, height: blk.height });
        }
        if (this.cachedAssets.has(blk.cache_name) || this.renderingDiagrams.has(blk.cache_name)) {
          continue;
        }
        const localFile = `${cacheDir}/${blk.cache_name}`;
        if (blk.rendered && (await fs.exists(localFile).catch(() => false))) {
          this.cachedAssets.add(blk.cache_name);
          updated = true;
          continue;
        }
        this.renderingDiagrams.add(blk.cache_name);
        const cName = blk.cache_name;
        const fmt = blk.format || "mermaid";
        cx.spawn(async (cx) => {
          try {
            const res = await exec(
              "herdr-obsidian",
              ["render-diagram", cName, "--note", noteRel, "--format", fmt],
              { cwd: target.cwd, on: target.on }
            );
            if (res.code === 0 && res.stdout) {
              const parsed = JSON.parse(res.stdout);
              if (parsed.ok && parsed.b64) {
                await fs.writeFile(localFile, decodeBase64(parsed.b64));
                if (parsed.width && parsed.height) {
                  this.diagramDims.set(cName, { width: parsed.width, height: parsed.height });
                }
                this.cachedAssets.add(cName);
                cx.notify();
              }
            }
          } catch {
          } finally {
            this.renderingDiagrams.delete(cName);
          }
        });
      }
    }

    if (updated) cx.notify();
  }

  refresh(cx, opts = {}) {
    const navUpdated = this.consumeSharedNav();
    if (navUpdated) {
      cx.notify();
    }
    const target = resolveWorkspaceTarget(this.lastTarget);
    const targetKey = `${target.on || "local"}:${target.spaceId || ""}:${target.cwd || ""}`;
    this.lastTargetKey = targetKey;

    if (this.loading && this.loadingTargetKey === targetKey && !opts.forceSync && !navUpdated) {
      this.pendingRefresh = {
        background: Boolean(opts.background && (this.pendingRefresh?.background ?? true)),
        forceSync: Boolean(opts.forceSync || navUpdated || this.pendingRefresh?.forceSync),
      };
      return;
    }
    if (target.cwd) {
      this.lastTarget = target;
      if (!target.on) {
        this.lastLocalCwd = target.cwd;
      }
    }
    if (!target.cwd) return;

    this.loading = true;
    this.loadingTargetKey = targetKey;
    const reqSeq = ++this.refreshSeq;
    const sidebarW = this.sidebarOpen ? 216 : 0;
    const inspectorW = this.inspectorOpen && this.viewMode === "note" ? 216 : 0;
    const availW = Math.max(360, Math.round((this.size?.width || 860) - sidebarW - inspectorW - 20));
    const availH = Math.max(260, Math.round((this.size?.height || 680) - 82));

    const buildArgs = (cwdArg, paneArg) => {
      const a = [
        "app-state",
        "--cwd",
        cwdArg,
        "--width",
        String(availW),
        "--height",
        String(availH),
        "--metric",
        this.treemapMetric,
        "--graph-mode",
        this.graphMode,
      ];
      if (this.activeNotePath) a.push("--note", this.activeNotePath);
      if (this.searchQuery) a.push("--query", this.searchQuery);
      if (this.tagFilter) a.push("--tag", this.tagFilter);
      if (this.levelFilter !== null) a.push("--level", String(this.levelFilter));
      if (this.categoryFilter) a.push("--category", this.categoryFilter);
      if (this.treemapZoomFolder) a.push("--zoom-folder", this.treemapZoomFolder);
      if (this.activeCanvasPath) a.push("--canvas", this.activeCanvasPath);
      if (this.activeTicket) a.push("--ticket", this.activeTicket);
      if (paneArg) a.push("--pane", paneArg);
      if (this.lastSpoolSeq > 0) a.push("--spool-seq", String(this.lastSpoolSeq));
      if (this.followSync || opts.forceSync || navUpdated) a.push("--follow-sync");
      return a;
    };

    cx.spawn(async (cx) => {
      try {
        const res = await exec("herdr-obsidian", buildArgs(target.cwd, target.pane), {
          cwd: target.cwd,
          on: target.on,
        }).catch((e) => ({ code: 127, stdout: "", stderr: String(e) }));

        if (reqSeq !== this.refreshSeq) return;

        if (res.code !== 0) {
          this.state = {
            ok: true,
            has_vault: false,
            vault_root: null,
            vault_name: null,
            cwd: target.cwd,
            stats: { total_notes: 0, total_canvases: 0, total_assets: 0, total_links: 0 },
            bookmarks: [],
            tree: [],
            canvases: [],
            active_note: null,
            search_results: [],
          };
          this.error = null;
          return;
        }
        const data = JSON.parse(res.stdout);
        const prevVaultRoot = this.state?.vault_root;
        this.state = data;
        this.error = null;

        if (data.has_vault === false || !data.vault_root) {
          this.activeNotePath = null;
          this.activeCanvasPath = null;
          return;
        }

        if (prevVaultRoot && data.vault_root && prevVaultRoot !== data.vault_root) {
          this.activeNotePath = data.active_note?.relpath || null;
          this.activeCanvasPath = data.canvas?.relpath || null;
          this.history = this.activeNotePath ? [this.activeNotePath] : [];
          this.historyIndex = this.activeNotePath ? 0 : -1;
        }

        if (
          (this.followSync || opts.forceSync) &&
          data.spool_seq &&
          data.spool_seq !== this.lastSpoolSeq
        ) {
          this.lastSpoolSeq = data.spool_seq;
          if (data.spool_view && VIEWS.some((v) => v.id === data.spool_view)) {
            this.viewMode = data.spool_view;
          }
          if (data.spool_ticket) {
            this.activeTicket = data.spool_ticket;
          }
          if (data.active_note?.relpath) {
            this.activeNotePath = data.active_note.relpath;
          }
          if (data.canvas?.relpath) {
            this.activeCanvasPath = data.canvas.relpath;
          }
        }

        if (data.active_note?.relpath && !this.activeNotePath) {
          this.activeNotePath = data.active_note.relpath;
          this.history = [this.activeNotePath];
          this.historyIndex = 0;
        }

        await this.ensureAllAssets(data, target, cx);

        if (this.editMode && data.active_note && this.editorNotePath !== data.active_note.relpath) {
          this.setupEditorForNote(data.active_note);
        }

        if (data.spool_dir) this.watchDirectory(data.spool_dir, "watchedSpool", cx);
        if (data.vault_root) this.watchDirectory(data.vault_root, "watchedVault", cx);
      } catch (e) {
        if (reqSeq === this.refreshSeq && !opts.background) this.error = String(e);
      } finally {
        if (reqSeq === this.refreshSeq) {
          this.loading = false;
          cx.notify();
          if (this.pendingRefresh) {
            const nextOpts = this.pendingRefresh;
            this.pendingRefresh = null;
            this.refresh(cx, nextOpts);
          }
        }
      }
    });
  }

  setupEditorForNote(note) {
    if (this.editorState) {
      this.editorState.release();
      this.editorState = null;
    }
    if (!note) return;
    const t = theme();
    this.editorNotePath = note.relpath;
    this.editorState = EditorState.new({
      language: "md",
      readonly: false,
      soft_wrap: true,
      line_numbers: true,
      value: note.raw_markdown || "",
      font_family: settings().font_family,
      font_size: 12.5,
      syntax: {
        keyword: t.ansi5,
        string: t.ansi2,
        comment: t.dim,
        function: t.ansi4,
        type: t.ansi3,
        number: t.ansi1,
        constant: t.ansi6,
      },
    });
  }

  toggleEditMode(cx) {
    const note = this.state?.active_note;
    if (!note) return;
    this.editMode = !this.editMode;
    if (this.editMode) {
      this.setupEditorForNote(note);
    } else if (this.editorState) {
      this.editorState.release();
      this.editorState = null;
      this.editorNotePath = null;
    }
    cx.notify();
  }

  saveEditedNote(cx) {
    const note = this.state?.active_note;
    if (!note || !this.editorState) return;
    const content = this.editorState.value();
    const target = resolveWorkspaceTarget(this.lastTarget);
    cx.spawn(async (cx) => {
      try {
        const res = await exec(
          "herdr-obsidian",
          ["write", note.relpath, "--content", content, "--json"],
          { cwd: target.cwd, on: target.on }
        );
        if (res.code === 0) {
          notify({
            title: "Vault saved",
            body: note.title,
            level: "success",
            timeout: 2200,
          });
          this.editMode = false;
          if (this.editorState) {
            this.editorState.release();
            this.editorState = null;
          }
          this.refresh(cx);
        } else {
          notify({
            title: "Save failed",
            body: res.stderr || "Could not write note",
            level: "error",
          });
        }
      } catch (e) {
        notify({ title: "Save failed", body: String(e), level: "error" });
      }
      cx.notify();
    });
  }

  openNote(relpath, cx, opts = {}) {
    if (!relpath) return;
    const cleaned = decodeURIComponent(String(relpath).replace(/^vault:\/\//, "")).split("#")[0];
    if (!cleaned) return;
    if (cleaned.startsWith("canvas/")) {
      this.activeCanvasPath = cleaned.slice("canvas/".length);
      this.viewMode = "canvas";
      this.panX = 0;
      this.panY = 0;
      this.refresh(cx);
      return;
    }
    if (cleaned.endsWith(".canvas")) {
      this.activeCanvasPath = cleaned;
      this.viewMode = "canvas";
      this.panX = 0;
      this.panY = 0;
      this.refresh(cx);
      return;
    }
    this.activeNotePath = cleaned;
    this.viewMode = "note";
    if (opts.edit) {
      this.editMode = true;
    } else if (this.editMode) {
      this.editMode = false;
      if (this.editorState) {
        this.editorState.release();
        this.editorState = null;
      }
    }
    if (opts.pushHistory !== false) {
      const trimmed = this.history.slice(0, this.historyIndex + 1);
      if (trimmed[trimmed.length - 1] !== cleaned) {
        trimmed.push(cleaned);
      }
      this.history = trimmed;
      this.historyIndex = trimmed.length - 1;
    }
    this.refresh(cx);
  }

  goBack(cx) {
    if (this.historyIndex > 0) {
      this.historyIndex -= 1;
      this.openNote(this.history[this.historyIndex], cx, { pushHistory: false });
    }
  }

  goForward(cx) {
    if (this.historyIndex + 1 < this.history.length) {
      this.historyIndex += 1;
      this.openNote(this.history[this.historyIndex], cx, { pushHistory: false });
    }
  }

  handleLinkClick(url, cx) {
    if (!url) return;
    const u = String(url);
    if (u.startsWith("vault://")) {
      this.openNote(u.slice("vault://".length), cx, { pushHistory: true });
      return;
    }
    if (!u.startsWith("http://") && !u.startsWith("https://") && !u.startsWith("mailto:")) {
      this.openNote(u, cx, { pushHistory: true });
    }
  }

  ensureLightboxAsset(cx) {
    const lb = this.lightbox;
    if (!lb?.cacheName) return;
    const cacheDir = `${appHome()}/data/obsidian-cache`;
    const localFile = `${cacheDir}/${lb.cacheName}`;
    const target = resolveWorkspaceTarget(this.lastTarget);

    cx.spawn(async (cx) => {
      try {
        await fs.mkdir(cacheDir, { recursive: true }).catch(() => {});
        if (await fs.exists(localFile).catch(() => false)) {
          this.lbReady = true;
          cx.notify();
          return;
        }
        if (lb.type === "diagram") {
          const res = await exec(
            "herdr-obsidian",
            [
              "render-diagram",
              lb.cacheName,
              "--note",
              lb.noteRel || "",
              "--format",
              lb.format || "mermaid",
            ],
            { cwd: target.cwd, on: target.on }
          );
          if (res.code === 0 && res.stdout) {
            const parsed = JSON.parse(res.stdout);
            if (parsed.ok && parsed.b64) {
              await fs.writeFile(localFile, decodeBase64(parsed.b64));
              if (parsed.width && parsed.height) {
                this.lightbox.width = parsed.width;
                this.lightbox.height = parsed.height;
              }
              this.lbReady = true;
              cx.notify();
            }
          }
        } else if (lb.relpath) {
          const res = await exec("herdr-obsidian", ["app-artifact", lb.relpath], {
            cwd: target.cwd,
            on: target.on,
          });
          if (res.code === 0 && res.stdout) {
            const parsed = JSON.parse(res.stdout);
            if (parsed.ok && parsed.b64) {
              await fs.writeFile(localFile, decodeBase64(parsed.b64));
              this.lbReady = true;
              cx.notify();
            }
          }
        }
      } catch {}
    });
  }

  openFigureFloat(item, _cx, kind = "window") {
    if (!item?.cacheName) return;
    openOverlay({
      mod: "herdr-obsidian",
      kind,
      key: kind === "window" ? "obsidian-figure-float" : undefined,
      width: kind === "window" ? 0.76 : 0.88,
      height: kind === "window" ? 0.76 : 0.86,
      props: {
        lightbox: item,
        lightboxKind: kind,
      },
    });
  }

  handleKeyDown(e, cx) {
    const key = e.key || e.keystroke?.key || "";
    const mods = e.modifiers || e.keystroke?.modifiers || {};
    if (this.isLightbox) {
      if (key === "escape" && props()?.overlay) {
        closeOverlay(props().overlay);
      } else if (key === "+" || key === "=") {
        this.lbZoom = Math.min(4.5, this.lbZoom * 1.2);
        cx.notify();
      } else if (key === "-") {
        this.lbZoom = Math.max(0.25, this.lbZoom / 1.2);
        cx.notify();
      } else if (key === "0") {
        this.lbZoom = 1.0;
        this.lbPanX = 0;
        this.lbPanY = 0;
        cx.notify();
      } else if (key === "s" && this.lightbox?.source) {
        this.lbShowSource = !this.lbShowSource;
        cx.notify();
      }
      return;
    }
    if (mods.control && key === "s" && this.editMode) {
      this.saveEditedNote(cx);
      return;
    }
    if (this.typing || this.editMode) {
      if (key === "escape" && this.typing) {
        this.typing = false;
        this.handle.focus();
        cx.stop_propagation();
        cx.notify();
      }
      return;
    }

    if (key === "/") {
      this.searchInput.focus();
      cx.notify();
    } else if (key === "1") {
      this.viewMode = "note";
      cx.notify();
    } else if (key === "2") {
      this.viewMode = "treemap";
      this.refresh(cx);
    } else if (key === "3") {
      this.viewMode = "graph";
      this.refresh(cx);
    } else if (key === "4") {
      this.viewMode = "canvas";
      this.refresh(cx);
    } else if (key === "5") {
      this.viewMode = "ticket";
      this.refresh(cx);
    } else if (key === "b") {
      this.sidebarOpen = !this.sidebarOpen;
      this.refresh(cx);
    } else if (key === "i") {
      this.inspectorOpen = !this.inspectorOpen;
      this.refresh(cx);
    } else if (key === "e") {
      this.toggleEditMode(cx);
    } else if (key === "r") {
      this.refresh(cx);
    } else if (key === "0") {
      this.panX = 0;
      this.panY = 0;
      this.zoom = 0.78;
      cx.notify();
    } else if (key === "+" || key === "=") {
      this.zoom = Math.min(2.2, this.zoom * 1.15);
      cx.notify();
    } else if (key === "-") {
      this.zoom = Math.max(0.28, this.zoom / 1.15);
      cx.notify();
    } else if (key === "escape" && props()?.overlay) {
      closeOverlay(props().overlay);
    }
  }

  renderHeader(t) {
    const canBack = this.historyIndex > 0;
    const canFwd = this.historyIndex + 1 < this.history.length;
    const hasFilter = Boolean(this.searchQuery || this.tagFilter || this.levelFilter !== null);

    return h_flex()
      .h(40)
      .w_full()
      .flex_none()
      .px(10)
      .gap(8)
      .items_center()
      .justify_between()
      .bg(t.chrome || t.surface)
      .border_b(1)
      .border_color(t.border)
      .child(
        // Left: Sidebar toggle, Back/Forward, and Segmented Mode Switcher
        h_flex()
          .gap(6)
          .items_center()
          .min_w(0)
          .child(
            ghostBtn("obs-toggle-sb", "◧", t, {
              active: this.sidebarOpen,
              onClick: (_e, cx) => {
                this.sidebarOpen = !this.sidebarOpen;
                this.refresh(cx);
              },
            })
          )
          .child(
            h_flex()
              .gap(2)
              .items_center()
              .child(
                ghostBtn("obs-nav-back", "‹", t, {
                  onClick: (_e, cx) => canBack && this.goBack(cx),
                })
              )
              .child(
                ghostBtn("obs-nav-fwd", "›", t, {
                  onClick: (_e, cx) => canFwd && this.goForward(cx),
                })
              )
          )
          .child(
            h_flex()
              .p(2)
              .gap(2)
              .items_center()
              .rounded(6)
              .bg(t.background)
              .border_1()
              .border_color(t.border)
              .children(
                VIEWS.map((v) => {
                  const selected = this.viewMode === v.id;
                  return div()
                    .id(`obs-mode-${v.id}`)
                    .h(22)
                    .px(9)
                    .flex()
                    .items_center()
                    .justify_center()
                    .rounded(4)
                    .cursor_pointer()
                    .text_size(11.5)
                    .when(selected, (el) =>
                      el.bg(t.selected).text_color(t.foreground).font_medium()
                    )
                    .when(!selected, (el) => el.text_color(t.muted))
                    .hover((s) => s.text_color(t.foreground))
                    .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
                    .on_click((_e, cx) => {
                      this.viewMode = v.id;
                      this.refresh(cx);
                    })
                    .child(v.label);
                })
              )
          )
      )
      .child(
        // Right: Search field + contextual action
        h_flex()
          .gap(6)
          .items_center()
          .flex_none()
          .when(Boolean(this.tagFilter), (el) =>
            el.child(
              ghostBtn("obs-clear-tag", `#${this.tagFilter} ×`, t, {
                active: true,
                onClick: (_e, cx) => {
                  this.tagFilter = null;
                  this.refresh(cx);
                },
              })
            )
          )
          .child(
            h_flex()
              .id("obs-search-box")
              .w(176)
              .h(26)
              .px(8)
              .gap(4)
              .items_center()
              .rounded(6)
              .bg(t.background)
              .border_1()
              .border_color(this.typing || hasFilter ? t.accent : t.border)
              .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
              .child(
                div()
                  .flex_1()
                  .min_w(0)
                  .h_full()
                  .child(Input.new(this.searchInput).h_full().text_size(11.5).text_color(t.foreground))
              )
              .when(hasFilter, (el) =>
                el.child(
                  div()
                    .id("obs-clear-filter")
                    .cursor_pointer()
                    .text_size(11)
                    .text_color(t.muted)
                    .hover((s) => s.text_color(t.foreground))
                    .on_click((_e, cx) => {
                      this.searchInput.set_value("");
                      this.searchQuery = "";
                      this.tagFilter = null;
                      this.levelFilter = null;
                      this.categoryFilter = null;
                      this.refresh(cx);
                    })
                    .child("×")
                )
              )
          )
          .when(this.viewMode === "note", (el) =>
            el
              .child(
                this.editMode
                  ? ghostBtn("obs-save-btn", "Save", t, {
                      primary: true,
                      onClick: (_e, cx) => this.saveEditedNote(cx),
                    })
                  : ghostBtn("obs-edit-btn", "Edit", t, {
                      onClick: (_e, cx) => this.toggleEditMode(cx),
                    })
              )
              .when(this.editMode, (e2) =>
                e2.child(
                  ghostBtn("obs-cancel-btn", "Cancel", t, {
                    onClick: (_e, cx) => this.toggleEditMode(cx),
                  })
                )
              )
              .child(
                ghostBtn("obs-outline-btn", "§ Outline", t, {
                  active: this.inspectorOpen,
                  onClick: (_e, cx) => {
                    this.inspectorOpen = !this.inspectorOpen;
                    this.refresh(cx);
                  },
                })
              )
          )
      );
  }

  renderLeftSidebar(t) {
    const bookmarks = this.state?.bookmarks || [];
    const tree = this.state?.tree || [];
    const searchHits = this.state?.search_results || [];
    const activeRel = this.state?.active_note?.relpath;

    return v_flex()
      .w(216)
      .flex_none()
      .h_full()
      .min_h(0)
      .bg(t.chrome || t.surface)
      .border_r(1)
      .border_color(t.border)
      .child(
        // Clean navigation header with quiet text tabs
        h_flex()
          .h(32)
          .w_full()
          .flex_none()
          .px(8)
          .justify_between()
          .items_center()
          .border_b(1)
          .border_color(t.border)
          .child(
            h_flex()
              .gap(2)
              .items_center()
              .children(
                [
                  { id: "mocs", label: "Pinned" },
                  { id: "tree", label: "Folders" },
                  { id: "search", label: "Search" },
                ].map((tab) => {
                  const sel = this.sidebarTab === tab.id;
                  return div()
                    .id(`obs-sb-tab-${tab.id}`)
                    .px(6)
                    .py(3)
                    .rounded(4)
                    .cursor_pointer()
                    .text_size(11)
                    .when(sel, (el) => el.bg(t.selected).text_color(t.foreground).font_medium())
                    .when(!sel, (el) => el.text_color(t.muted))
                    .hover((s) => s.text_color(t.foreground))
                    .on_click((_e, cx) => {
                      this.sidebarTab = tab.id;
                      cx.notify();
                    })
                    .child(tab.label);
                })
              )
          )
          .child(
            div()
              .text_size(10.5)
              .text_color(t.dim)
              .child(
                this.sidebarTab === "search"
                  ? `${searchHits.length}`
                  : `${this.state?.stats?.total_notes || 0}`
              )
          )
      )
      .when(this.sidebarTab === "search" || this.levelFilter !== null, (el) =>
        el.child(
          h_flex()
            .h(26)
            .w_full()
            .flex_none()
            .px(8)
            .gap(4)
            .items_center()
            .border_b(1)
            .border_color(t.border)
            .child(div().text_size(10).text_color(t.dim).child("Tier:"))
            .children(
              [null, 0, 1, 2, 3].map((lvl) => {
                const sel = this.levelFilter === lvl;
                const lbl = lvl === null ? "All" : `L${lvl}`;
                return div()
                  .id(`obs-tier-${lvl ?? "all"}`)
                  .px(5)
                  .py(2)
                  .rounded(3)
                  .cursor_pointer()
                  .text_size(10)
                  .when(sel, (e2) => e2.bg(t.selected).text_color(t.accent).font_semibold())
                  .when(!sel, (e2) => e2.text_color(t.muted))
                  .hover((s) => s.text_color(t.foreground))
                  .on_click((_e, cx) => {
                    this.levelFilter = lvl;
                    if (lvl !== null) this.sidebarTab = "search";
                    this.refresh(cx);
                  })
                  .child(lbl);
              })
            )
        )
      )
      .child(
        v_flex()
          .id("obs-sidebar-scroll")
          .flex_1()
          .w_full()
          .h_full()
          .min_h(0)
          .overflow_y_scrollbar()
          .p(6)
          .gap(2)
          .when(this.sidebarTab === "mocs", (el) =>
            el.children(
              bookmarks.map((bm, idx) => {
                const isSelected = bm.path === activeRel || bm.path === this.activeCanvasPath;
                const cleanTitle = String(bm.title || "")
                  .replace(/^\d+\s*-\s*/, "")
                  .replace(/\s*Map-Of-Content\s*\(MOC\)/i, "");
                return h_flex()
                  .id(`obs-bm-${idx}`)
                  .w_full()
                  .h(27)
                  .flex_none()
                  .px(8)
                  .gap(7)
                  .items_center()
                  .rounded(6)
                  .cursor_pointer()
                  .when(isSelected, (r) => r.bg(t.selected))
                  .hover((s) => s.bg(t.hover))
                  .on_click((_e, cx) => this.openNote(bm.path, cx, { pushHistory: true }))
                  .child(
                    div()
                      .w(5)
                      .h(5)
                      .rounded_full()
                      .flex_none()
                      .bg(bm.kind === "canvas" ? "#c49644" : isSelected ? t.accent : t.dim)
                  )
                  .child(
                    div()
                      .flex_1()
                      .min_w(0)
                      .truncate()
                      .text_size(12)
                      .when(isSelected, (c) => c.font_medium().text_color(t.foreground))
                      .when(!isSelected, (c) => c.text_color(t.muted))
                      .child(cleanTitle || String(bm.title || "Note"))
                  );
              })
            )
          )
          .when(this.sidebarTab === "tree", (el) =>
            el.children(
              tree.flatMap((grp) => {
                const isOpen = this.openFolders.has(grp.folder);
                const cleanFolder = String(grp.folder || "").replace(/^\d+-/, "");
                const header = h_flex()
                  .id(`obs-fld-${grp.folder}`)
                  .w_full()
                  .h(27)
                  .flex_none()
                  .px(6)
                  .gap(6)
                  .items_center()
                  .rounded(6)
                  .cursor_pointer()
                  .hover((s) => s.bg(t.hover))
                  .on_click((_e, cx) => {
                    if (this.openFolders.has(grp.folder)) {
                      this.openFolders.delete(grp.folder);
                    } else {
                      this.openFolders.add(grp.folder);
                    }
                    cx.notify();
                  })
                  .child(
                    div()
                      .w(10)
                      .flex_none()
                      .text_size(10)
                      .text_color(t.dim)
                      .child(isOpen ? "▾" : "▸")
                  )
                  .child(
                    div()
                      .flex_1()
                      .min_w(0)
                      .truncate()
                      .font_medium()
                      .text_size(12)
                      .text_color(t.foreground)
                      .child(cleanFolder || String(grp.folder || "Root"))
                  )
                  .child(
                    div().flex_none().text_size(10.5).text_color(t.dim).child(String(grp.count || 0))
                  );

                if (!isOpen) return [header];
                const children = (grp.items || []).map((item) => {
                  const sel = item.relpath === activeRel;
                  return h_flex()
                    .id(`obs-tree-item-${item.relpath}`)
                    .w_full()
                    .h(25)
                    .flex_none()
                    .pl(20)
                    .pr(6)
                    .gap(6)
                    .items_center()
                    .rounded(5)
                    .cursor_pointer()
                    .when(sel, (r) => r.bg(t.selected))
                    .hover((s) => s.bg(t.hover))
                    .on_click((_e, cx) => this.openNote(item.relpath, cx, { pushHistory: true }))
                    .when(item.level !== null && item.level !== undefined, (row) =>
                      row.child(
                        div()
                          .flex_none()
                          .text_size(10)
                          .font_medium()
                          .text_color(levelTint(item.level, t))
                          .child(`L${item.level}`)
                      )
                    )
                    .child(
                      div()
                        .flex_1()
                        .min_w(0)
                        .truncate()
                        .text_size(11.5)
                        .text_color(sel ? t.foreground : t.muted)
                        .child(String(item.title || ""))
                    );
                });
                return [header, ...children];
              })
            )
          )
          .when(this.sidebarTab === "search", (el) =>
            el.children(
              searchHits.map((hit, idx) => {
                const sel = hit.relpath === activeRel;
                return v_flex()
                  .id(`obs-hit-${idx}`)
                  .w_full()
                  .flex_none()
                  .px(8)
                  .py(6)
                  .gap(2)
                  .rounded(6)
                  .cursor_pointer()
                  .when(sel, (r) => r.bg(t.selected))
                  .hover((s) => s.bg(t.hover))
                  .on_click((_e, cx) => this.openNote(hit.relpath, cx, { pushHistory: true }))
                  .child(
                    h_flex()
                      .w_full()
                      .gap(5)
                      .items_center()
                      .when(hit.level !== null && hit.level !== undefined, (r) =>
                        r.child(
                          div()
                            .flex_none()
                            .text_size(10)
                            .font_semibold()
                            .text_color(levelTint(hit.level, t))
                            .child(`L${hit.level}`)
                        )
                      )
                      .child(
                        div()
                          .flex_1()
                          .min_w(0)
                          .truncate()
                          .font_medium()
                          .text_size(12)
                          .text_color(sel ? t.foreground : t.muted)
                          .child(String(hit.title || ""))
                      )
                  )
                  .when(Boolean(hit.snippet), (c) =>
                    c.child(
                      div()
                        .w_full()
                        .truncate()
                        .text_size(10.5)
                        .text_color(t.dim)
                        .child(String(hit.snippet || ""))
                    )
                  );
              })
            )
          )
      );
  }

  renderNoteBlock(blk, idx, note, t) {
    if (blk.type === "callout") {
      const tone = calloutTone(blk.kind, t);
      return v_flex()
        .id(`obs-blk-callout-${idx}`)
        .w_full()
        .flex_none()
        .p(12)
        .gap(6)
        .rounded(7)
        .bg(t.surface)
        .border_1()
        .border_color(t.border)
        .child(
          h_flex()
            .w_full()
            .gap(8)
            .items_center()
            .child(
              div()
                .text_size(10.5)
                .font_semibold()
                .text_color(tone)
                .child(String(blk.kind || "NOTE").toUpperCase())
            )
            .when(Boolean(blk.title), (el) =>
              el.child(
                div()
                  .flex_1()
                  .min_w(0)
                  .font_medium()
                  .text_size(12.5)
                  .text_color(t.foreground)
                  .child(String(blk.title || ""))
              )
            )
        )
        .when(Boolean(blk.content), (el) =>
          el.child(
            div()
              .w_full()
              .flex_none()
              .child(
                TextView.markdown(`obs-callout-md-${note.relpath}-${idx}`, String(blk.content || ""))
                  .selectable(true)
                  .on_link_click((url, cx) => this.handleLinkClick(url, cx))
              )
          )
        );
    }

    if (blk.type === "image") {
      const hasCached = this.cachedAssets.has(blk.cache_name);
      const sidebarW = this.sidebarOpen ? 216 : 0;
      const inspectorW = this.inspectorOpen ? 216 : 0;
      const maxW = Math.max(280, Math.min(760, (this.size?.width || 860) - sidebarW - inspectorW - 72));
      const naturalW = blk.width || 680;
      const naturalH = blk.height || 380;
      const ratio = naturalW > 0 ? naturalH / naturalW : 0.56;
      const drawW = Math.round(Math.min(maxW, naturalW));
      const drawH = Math.max(100, Math.min(480, Math.round(drawW * ratio)));
      const floatItem = {
        type: "image",
        cacheName: blk.cache_name,
        title: String(blk.caption || blk.relpath || "Figure"),
        subtitle: String(blk.relpath || ""),
        format: String(blk.ext || ".svg").replace(".", "").toUpperCase(),
        width: naturalW,
        height: naturalH,
        relpath: blk.relpath,
      };

      return v_flex()
        .id(`obs-blk-img-${idx}`)
        .w_full()
        .flex_none()
        .p(12)
        .gap(8)
        .rounded(8)
        .bg(t.surface)
        .border_1()
        .border_color(t.border)
        .items_center()
        .child(
          h_flex()
            .w_full()
            .justify_between()
            .items_center()
            .child(
              h_flex()
                .gap(8)
                .items_center()
                .min_w(0)
                .child(
                  div()
                    .flex_none()
                    .text_size(10.5)
                    .font_semibold()
                    .text_color(t.accent)
                    .child(floatItem.format)
                )
                .child(
                  div()
                    .truncate()
                    .text_size(11.5)
                    .text_color(t.muted)
                    .child(String(blk.caption || blk.relpath || ""))
                )
            )
            .child(
              ghostBtn(`obs-expand-img-${idx}`, "Expand ↗", t, {
                onClick: (_e, cx) => this.openFigureFloat(floatItem, cx, "window"),
              })
            )
        )
        .child(
          hasCached
            ? div()
                .id(`obs-blk-img-hit-${idx}`)
                .w_full()
                .flex_none()
                .flex()
                .justify_center()
                .cursor_pointer()
                .on_click((_e, cx) => this.openFigureFloat(floatItem, cx, "window"))
                .child(image(`data/obsidian-cache/${blk.cache_name}`).w(drawW).h(drawH))
            : div()
                .p(12)
                .text_size(11.5)
                .text_color(t.muted)
                .child(`Loading figure: ${blk.relpath || ""}`)
        );
    }

    if (blk.type === "diagram") {
      const cName = blk.cache_name || "";
      const hasRendered = Boolean(cName && this.cachedAssets.has(cName));
      const showSource = Boolean(cName && this.diagramShowSource.has(cName));
      const isRendering = Boolean(cName && this.renderingDiagrams.has(cName));
      const dims = (cName && this.diagramDims.get(cName)) || {
        width: blk.width || 1600,
        height: blk.height || 480,
      };
      const sidebarW = this.sidebarOpen ? 216 : 0;
      const inspectorW = this.inspectorOpen ? 216 : 0;
      const maxW = Math.max(280, Math.min(760, (this.size?.width || 860) - sidebarW - inspectorW - 72));
      const ratio = dims.width > 0 ? dims.height / dims.width : 0.35;
      const drawW = Math.round(maxW);
      const drawH = Math.max(100, Math.min(520, Math.round(drawW * ratio)));
      const floatItem = {
        type: "diagram",
        cacheName: cName,
        title: String(blk.title || "Architecture Diagram"),
        subtitle: String(note.title || ""),
        format: String(blk.format || "mermaid"),
        source: String(blk.source || ""),
        width: dims.width,
        height: dims.height,
        noteRel: note.relpath,
      };

      return v_flex()
        .id(`obs-blk-diag-${idx}`)
        .w_full()
        .flex_none()
        .p(12)
        .gap(8)
        .rounded(8)
        .bg(t.surface)
        .border_1()
        .border_color(t.border)
        .child(
          h_flex()
            .w_full()
            .justify_between()
            .items_center()
            .child(
              h_flex()
                .gap(8)
                .items_center()
                .child(
                  div()
                    .text_size(10.5)
                    .font_semibold()
                    .text_color(t.accent)
                    .child(String(blk.format || "mermaid").toUpperCase())
                )
                .child(
                  div()
                    .text_size(11.5)
                    .text_color(t.muted)
                    .child(
                      isRendering && !hasRendered
                        ? "Rendering diagram…"
                        : "Diagram · Click to expand"
                    )
                )
            )
            .child(
              h_flex()
                .gap(4)
                .items_center()
                .when(hasRendered, (el) =>
                  el.child(
                    ghostBtn(`obs-toggle-diag-src-${idx}`, showSource ? "Diagram" : "Source", t, {
                      active: showSource,
                      onClick: (_e, cx) => {
                        if (this.diagramShowSource.has(cName)) {
                          this.diagramShowSource.delete(cName);
                        } else {
                          this.diagramShowSource.add(cName);
                        }
                        cx.notify();
                      },
                    })
                  )
                )
                .child(
                  ghostBtn(`obs-render-diag-${idx}`, "Expand ↗", t, {
                    onClick: (_e, cx) => this.openFigureFloat(floatItem, cx, "window"),
                  })
                )
            )
        )
        .child(
          hasRendered && !showSource
            ? div()
                .id(`obs-blk-diag-hit-${idx}`)
                .w_full()
                .flex_none()
                .flex()
                .justify_center()
                .py(4)
                .cursor_pointer()
                .on_click((_e, cx) => this.openFigureFloat(floatItem, cx, "window"))
                .child(image(`data/obsidian-cache/${cName}`).w(drawW).h(drawH))
            : div()
                .w_full()
                .flex_none()
                .child(
                  TextView.markdown(
                    `obs-diag-code-${note.relpath}-${idx}`,
                    `\`\`\`${blk.format || "mermaid"}\n${blk.source || ""}\n\`\`\``
                  ).selectable(true)
                )
        );
    }

    if (blk.type === "transclusion") {
      return v_flex()
        .id(`obs-blk-trans-${idx}`)
        .w_full()
        .flex_none()
        .p(12)
        .gap(4)
        .rounded(7)
        .cursor_pointer()
        .bg(t.surface)
        .border_1()
        .border_color(t.border)
        .hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => this.openNote(blk.relpath, cx, { pushHistory: true }))
        .child(
          h_flex()
            .w_full()
            .gap(8)
            .items_center()
            .child(
              div()
                .text_size(10)
                .font_semibold()
                .text_color(t.accent)
                .child("TRANSCLUDED")
            )
            .child(
              div()
                .flex_1()
                .min_w(0)
                .truncate()
                .font_medium()
                .text_size(12)
                .text_color(t.foreground)
                .child(String(blk.title || ""))
            )
        )
        .when(Boolean(blk.excerpt), (el) =>
          el.child(div().text_size(11.5).text_color(t.muted).child(String(blk.excerpt || "")))
        );
    }

    return div()
      .w_full()
      .flex_none()
      .child(
        TextView.markdown(`obs-md-${note.relpath}-${idx}`, String(blk.content || ""))
          .selectable(true)
          .on_link_click((url, cx) => this.handleLinkClick(url, cx))
      );
  }

  renderNoteConnectionsFooter(note, t) {
    const backlinks = note.backlinks || [];
    const outLinks = note.out_links || [];
    if (backlinks.length === 0 && outLinks.length === 0) {
      return div().h(8).flex_none();
    }

    return v_flex()
      .w_full()
      .flex_none()
      .pt(18)
      .mt(12)
      .gap(12)
      .border_t(1)
      .border_color(t.border)
      .when(backlinks.length > 0, (el) =>
        el.child(
          v_flex()
            .w_full()
            .gap(6)
            .child(
              div()
                .text_size(11.5)
                .font_semibold()
                .text_color(t.muted)
                .child(`Linked Mentions (${backlinks.length})`)
            )
            .children(
              backlinks.slice(0, 12).map((bl, idx) =>
                v_flex()
                  .id(`obs-foot-bl-${idx}`)
                  .w_full()
                  .px(10)
                  .py(7)
                  .gap(2)
                  .rounded(6)
                  .cursor_pointer()
                  .bg(t.surface)
                  .hover((s) => s.bg(t.hover))
                  .on_click((_e, cx) => this.openNote(bl.source, cx, { pushHistory: true }))
                  .child(
                    h_flex()
                      .w_full()
                      .gap(6)
                      .items_center()
                      .when(bl.level !== null && bl.level !== undefined, (r) =>
                        r.child(
                          div()
                            .text_size(10)
                            .font_semibold()
                            .text_color(levelTint(bl.level, t))
                            .child(`L${bl.level}`)
                        )
                      )
                      .child(
                        div()
                          .flex_1()
                          .min_w(0)
                          .truncate()
                          .font_medium()
                          .text_size(12)
                          .text_color(t.foreground)
                          .child(String(bl.title || ""))
                      )
                  )
                  .when(Boolean(bl.snippet), (c) =>
                    c.child(
                      div()
                        .w_full()
                        .truncate()
                        .text_size(11)
                        .text_color(t.dim)
                        .child(String(bl.snippet || ""))
                    )
                  )
              )
            )
        )
      )
      .when(outLinks.length > 0, (el) =>
        el.child(
          v_flex()
            .w_full()
            .gap(6)
            .child(
              div()
                .text_size(11.5)
                .font_semibold()
                .text_color(t.muted)
                .child(`Outgoing References (${outLinks.length})`)
            )
            .child(
              h_flex()
                .w_full()
                .gap(6)
                .flex_wrap()
                .children(
                  outLinks.slice(0, 18).map((ol, idx) =>
                    h_flex()
                      .id(`obs-foot-ol-${idx}`)
                      .px(8)
                      .py(4)
                      .gap(5)
                      .items_center()
                      .rounded(5)
                      .cursor_pointer()
                      .bg(t.surface)
                      .hover((s) => s.bg(t.hover))
                      .on_click((_e, cx) => this.openNote(ol.relpath, cx, { pushHistory: true }))
                      .when(ol.level !== null && ol.level !== undefined, (r) =>
                        r.child(
                          div()
                            .text_size(9.5)
                            .font_semibold()
                            .text_color(levelTint(ol.level, t))
                            .child(`L${ol.level}`)
                        )
                      )
                      .child(
                        div()
                          .max_w(240)
                          .truncate()
                          .text_size(11.5)
                          .text_color(t.muted)
                          .child(String(ol.title || ""))
                      )
                  )
                )
            )
        )
      );
  }

  renderNoteOutlineDrawer(note, t) {
    const headings = note?.headings || [];
    const backlinks = note?.backlinks || [];

    return v_flex()
      .w(216)
      .flex_none()
      .h_full()
      .min_h(0)
      .bg(t.chrome || t.surface)
      .border_l(1)
      .border_color(t.border)
      .child(
        h_flex()
          .h(32)
          .w_full()
          .flex_none()
          .px(10)
          .items_center()
          .justify_between()
          .border_b(1)
          .border_color(t.border)
          .child(div().text_size(11.5).font_medium().text_color(t.foreground).child("Outline"))
          .child(
            div().text_size(10.5).text_color(t.dim).child(`${headings.length} sections`)
          )
      )
      .child(
        v_flex()
          .id("obs-inspector-scroll")
          .flex_1()
          .w_full()
          .h_full()
          .min_h(0)
          .overflow_y_scrollbar()
          .p(8)
          .gap(3)
          .children(
            headings.map((h, idx) =>
              h_flex()
                .id(`obs-hd-${idx}`)
                .w_full()
                .flex_none()
                .pl(4 + Math.max(0, (h.level || 1) - 1) * 10)
                .pr(6)
                .py(3)
                .gap(6)
                .items_center()
                .rounded(4)
                .child(
                  div()
                    .flex_1()
                    .min_w(0)
                    .truncate()
                    .text_size(h.level <= 2 ? 11.5 : 11)
                    .when(h.level <= 2, (c) => c.font_medium().text_color(t.foreground))
                    .when(h.level > 2, (c) => c.text_color(t.muted))
                    .child(String(h.text || ""))
                )
            )
          )
          .when(backlinks.length > 0, (el) =>
            el
              .child(
                div()
                  .pt(10)
                  .pb(4)
                  .px(4)
                  .text_size(11)
                  .font_medium()
                  .text_color(t.muted)
                  .child(`Backlinks (${backlinks.length})`)
              )
              .children(
                backlinks.map((bl, idx) =>
                  h_flex()
                    .id(`obs-insp-bl-${idx}`)
                    .w_full()
                    .flex_none()
                    .px(6)
                    .py(4)
                    .gap(5)
                    .items_center()
                    .rounded(5)
                    .cursor_pointer()
                    .hover((s) => s.bg(t.hover))
                    .on_click((_e, cx) => this.openNote(bl.source, cx, { pushHistory: true }))
                    .when(bl.level !== null && bl.level !== undefined, (r) =>
                      r.child(
                        div()
                          .text_size(9.5)
                          .font_semibold()
                          .text_color(levelTint(bl.level, t))
                          .child(`L${bl.level}`)
                      )
                    )
                    .child(
                      div()
                        .flex_1()
                        .min_w(0)
                        .truncate()
                        .text_size(11.5)
                        .text_color(t.muted)
                        .child(String(bl.title || ""))
                    )
                )
              )
          )
      );
  }

  renderNoteView(t) {
    const note = this.state?.active_note;
    if (!note) {
      return v_flex()
        .flex_1()
        .w_full()
        .h_full()
        .items_center()
        .justify_center()
        .child(
          div()
            .text_size(13)
            .text_color(t.muted)
            .child(this.loading ? "Indexing Obsidian Vault…" : "Select a note from the sidebar")
        );
    }

    const tags = note.tags || [];
    const blocks = note.blocks || [];
    const folderLabel = note.folder ? String(note.folder).replace(/^\d+-/, "") : "Vault Root";

    return h_flex()
      .flex_1()
      .w_full()
      .h_full()
      .min_w(0)
      .min_h(0)
      .child(
        v_flex()
          .flex_1()
          .w_full()
          .h_full()
          .min_w(0)
          .min_h(0)
          .child(
            this.editMode && this.editorState
              ? Editor.new(this.editorState).flex_1().w_full().h_full().min_h(0)
              : v_flex()
                  .id("obs-note-reader-scroll")
                  .flex_1()
                  .w_full()
                  .h_full()
                  .min_h(0)
                  .overflow_y_scrollbar()
                  .px(24)
                  .py(20)
                  .gap(14)
                  .child(
                    // Editorial Document Header (replaces the noisy rainbow badge strip)
                    v_flex()
                      .w_full()
                      .flex_none()
                      .pb(14)
                      .gap(6)
                      .border_b(1)
                      .border_color(t.border)
                      .child(
                        h_flex()
                          .w_full()
                          .justify_between()
                          .items_center()
                          .child(
                            h_flex()
                              .gap(6)
                              .items_center()
                              .when(note.level !== null && note.level !== undefined, (el) =>
                                el.child(
                                  div()
                                    .text_size(11)
                                    .font_semibold()
                                    .text_color(levelTint(note.level, t))
                                    .child(`L${note.level}`)
                                )
                              )
                              .child(
                                div()
                                  .text_size(11.5)
                                  .text_color(t.dim)
                                  .child(
                                    `${folderLabel}  ·  ${note.line_count || 0} lines  ·  ${
                                      (note.backlinks?.length || 0) + (note.out_links?.length || 0)
                                    } links`
                                  )
                              )
                          )
                          .when(tags.length > 0, (el) =>
                            el.child(
                              h_flex()
                                .gap(8)
                                .items_center()
                                .children(
                                  tags.slice(0, 5).map((tg) =>
                                    div()
                                      .id(`obs-tag-${tg}`)
                                      .cursor_pointer()
                                      .text_size(11)
                                      .text_color(this.tagFilter === tg ? t.accent : t.dim)
                                      .hover((s) => s.text_color(t.accent))
                                      .on_click((_e, cx) => {
                                        this.tagFilter = this.tagFilter === tg ? null : tg;
                                        this.sidebarOpen = true;
                                        this.sidebarTab = "search";
                                        this.refresh(cx);
                                      })
                                      .child(`#${tg}`)
                                  )
                                )
                            )
                          )
                      )
                      .child(
                        div()
                          .w_full()
                          .font_semibold()
                          .text_size(18)
                          .text_color(t.foreground)
                          .child(String(note.title || ""))
                      )
                  )
                  .children(blocks.map((blk, idx) => this.renderNoteBlock(blk, idx, note, t)))
                  .child(this.renderNoteConnectionsFooter(note, t))
          )
      )
      .when(Boolean(this.inspectorOpen), (el) => el.child(this.renderNoteOutlineDrawer(note, t)));
  }

  renderTreemapView(t) {
    const tm = this.state?.treemap;
    if (!tm) {
      return v_flex()
        .flex_1()
        .w_full()
        .h_full()
        .items_center()
        .justify_center()
        .child(div().text_color(t.muted).child("Loading DiskTree Treemap…"));
    }
    const groups = tm.groups || [];
    const cells = tm.cells || [];
    const hovered = this.hoveredTreemapCell;

    return v_flex()
      .flex_1()
      .w_full()
      .h_full()
      .min_w(0)
      .min_h(0)
      .child(
        // Clean sub-bar: Metric switcher + Zoom folder breadcrumb + Legend
        h_flex()
          .h(32)
          .w_full()
          .flex_none()
          .px(12)
          .gap(8)
          .items_center()
          .justify_between()
          .bg(t.surface)
          .border_b(1)
          .border_color(t.border)
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(div().text_size(11).text_color(t.dim).child("Metric:"))
              .children(
                [
                  { id: "bytes", label: "Bytes" },
                  { id: "lines", label: "Lines" },
                  { id: "links", label: "Links" },
                ].map((m) =>
                  ghostBtn(`obs-tm-metric-${m.id}`, m.label, t, {
                    active: this.treemapMetric === m.id,
                    onClick: (_e, cx) => {
                      this.treemapMetric = m.id;
                      this.refresh(cx);
                    },
                  })
                )
              )
              .when(Boolean(this.treemapZoomFolder), (el) =>
                el.child(
                  ghostBtn("obs-tm-zoom-out", `↑ All Folders (${this.treemapZoomFolder})`, t, {
                    primary: true,
                    onClick: (_e, cx) => {
                      this.treemapZoomFolder = "";
                      this.refresh(cx);
                    },
                  })
                )
              )
          )
          .child(
            h_flex()
              .gap(10)
              .items_center()
              .children(
                (tm.categories || []).slice(0, 7).map((cat) =>
                  h_flex()
                    .gap(4)
                    .items_center()
                    .child(div().w(7).h(7).rounded_full().bg(cat.color))
                    .child(div().text_size(10.5).text_color(t.muted).child(String(cat.short || "")))
                )
              )
          )
      )
      .child(
        // Full-height Squarified DiskTree Canvas with restrained dark-mode surface tints
        div()
          .id("obs-treemap-canvas")
          .flex_1()
          .w_full()
          .h_full()
          .min_h(0)
          .relative()
          .overflow_hidden()
          .bg(t.background)
          .m(8)
          .rounded(6)
          .children(
            groups.map((grp, gIdx) => {
              const cleanLabel = String(grp.label || "").replace(/^\d+-/, "");
              return div()
                .id(`obs-tm-grp-${gIdx}`)
                .absolute()
                .left(grp.x)
                .top(grp.y)
                .w(grp.w)
                .h(grp.h)
                .rounded(5)
                .bg(t.background)
                .border_1()
                .border_color(grp.border || t.border)
                .overflow_hidden()
                .when(grp.h >= 36 && grp.w >= 70, (el) =>
                  el.child(
                    h_flex()
                      .id(`obs-tm-grp-hdr-${gIdx}`)
                      .h(20)
                      .w_full()
                      .px(7)
                      .items_center()
                      .justify_between()
                      .cursor_pointer()
                      .bg(grp.fill || t.surface)
                      .border_b(1)
                      .border_color(grp.border || t.border)
                      .on_click((_e, cx) => {
                        if (grp.folder) {
                          this.treemapZoomFolder =
                            this.treemapZoomFolder === grp.folder ? "" : grp.folder;
                          this.refresh(cx);
                        }
                      })
                      .child(
                        h_flex()
                          .gap(5)
                          .items_center()
                          .min_w(0)
                          .child(div().w(6).h(6).rounded_full().flex_none().bg(grp.color))
                          .child(
                            div()
                              .truncate()
                              .font_semibold()
                              .text_size(10.5)
                              .text_color(t.foreground)
                              .child(cleanLabel || String(grp.label || ""))
                          )
                      )
                      .child(
                        div()
                          .flex_none()
                          .text_size(9.5)
                          .text_color(t.muted)
                          .child(String(grp.count || 0))
                      )
                  )
                );
            })
          )
          .children(
            cells.map((cell, cIdx) => {
              const isActive = cell.relpath === this.activeNotePath;
              const isHovered = hovered && hovered.relpath === cell.relpath;
              return v_flex()
                .id(`obs-tm-cell-${cIdx}`)
                .absolute()
                .left(cell.x)
                .top(cell.y)
                .w(cell.w)
                .h(cell.h)
                .p(cell.w >= 52 && cell.h >= 26 ? 5 : 2)
                .rounded(3)
                .overflow_hidden()
                .cursor_pointer()
                .bg(isActive ? t.selected : isHovered ? t.hover : cell.fill || t.surface)
                .border_1()
                .border_color(
                  isActive
                    ? t.accent
                    : isHovered
                    ? cell.color || t.accent
                    : cell.border || t.border
                )
                .on_hover((h, cx) => {
                  this.hoveredTreemapCell = h ? cell : null;
                  cx.notify();
                })
                .on_click((_e, cx) => this.openNote(cell.relpath, cx, { pushHistory: true }))
                .when(cell.w >= 54 && cell.h >= 22, (el) =>
                  el.child(
                    div()
                      .w_full()
                      .truncate()
                      .font_medium()
                      .text_size(10.5)
                      .text_color(t.foreground)
                      .child(String(cell.title || ""))
                  )
                )
                .when(cell.w >= 84 && cell.h >= 40, (el) =>
                  el.child(
                    div()
                      .w_full()
                      .truncate()
                      .text_size(9.5)
                      .text_color(t.muted)
                      .child(
                        `${cell.level !== null && cell.level !== undefined ? "L" + cell.level + " · " : ""}${
                          cell.line_count
                        }L · ${cell.links} links`
                      )
                  )
                );
            })
          )
      )
      .child(
        h_flex()
          .h(26)
          .w_full()
          .flex_none()
          .px(12)
          .items_center()
          .justify_between()
          .bg(t.chrome || t.surface)
          .border_t(1)
          .border_color(t.border)
          .child(
            div()
              .truncate()
              .text_size(11)
              .text_color(hovered ? t.foreground : t.dim)
              .child(
                hovered
                  ? `${hovered.title}  —  ${hovered.relpath} (${hovered.line_count} lines · ${hovered.links} links)`
                  : "Click any cell to read note  ·  Click a folder header to zoom in"
              )
          )
          .child(
            div()
              .flex_none()
              .text_size(10.5)
              .text_color(t.muted)
              .child(`${tm.total_notes || 0} notes`)
          )
      );
  }

  renderGraphView(t) {
    const gr = this.state?.graph;
    if (!gr) {
      return v_flex()
        .flex_1()
        .w_full()
        .h_full()
        .items_center()
        .justify_center()
        .child(div().text_color(t.muted).child("Loading Knowledge Graph…"));
    }
    const nodes = gr.nodes || [];
    const edges = gr.edges || [];
    const bounds = gr.bounds || { vb_x: -600, vb_y: -420, vb_w: 1200, vb_h: 840 };
    const scale = this.zoom;
    const sidebarW = this.sidebarOpen ? 216 : 0;
    const viewW = Math.max(360, (this.size?.width || 860) - sidebarW);
    const viewH = Math.max(260, (this.size?.height || 680) - 72);
    const centerX = Math.round(viewW / 2 + this.panX);
    const centerY = Math.round(viewH / 2 + this.panY);

    const svgLeft = Math.round(centerX + bounds.vb_x * scale);
    const svgTop = Math.round(centerY + bounds.vb_y * scale);
    const svgW = Math.max(100, Math.round(bounds.vb_w * scale));
    const svgH = Math.max(100, Math.round(bounds.vb_h * scale));
    const hasSvg = gr.svg_cache_name && this.cachedAssets.has(gr.svg_cache_name);

    return v_flex()
      .flex_1()
      .w_full()
      .h_full()
      .min_w(0)
      .min_h(0)
      .child(
        h_flex()
          .h(32)
          .w_full()
          .flex_none()
          .px(12)
          .gap(6)
          .items_center()
          .justify_between()
          .bg(t.surface)
          .border_b(1)
          .border_color(t.border)
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(
                ghostBtn("obs-gr-local", "Local Ego-Graph", t, {
                  active: this.graphMode === "local",
                  onClick: (_e, cx) => {
                    this.graphMode = "local";
                    this.panX = 0;
                    this.panY = 0;
                    this.refresh(cx);
                  },
                })
              )
              .child(
                ghostBtn("obs-gr-global", "Global Hierarchy (L0 → L3)", t, {
                  active: this.graphMode === "global",
                  onClick: (_e, cx) => {
                    this.graphMode = "global";
                    this.panX = 0;
                    this.panY = 0;
                    this.refresh(cx);
                  },
                })
              )
          )
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(
                div()
                  .pr(6)
                  .text_size(11)
                  .text_color(t.dim)
                  .child(`${nodes.length} nodes · ${edges.length} links`)
              )
              .child(
                ghostBtn("obs-gr-zout", "−", t, {
                  onClick: (_e, cx) => {
                    this.zoom = Math.max(0.28, this.zoom / 1.15);
                    cx.notify();
                  },
                })
              )
              .child(
                ghostBtn("obs-gr-zreset", `${Math.round(this.zoom * 100)}%`, t, {
                  onClick: (_e, cx) => {
                    this.panX = 0;
                    this.panY = 0;
                    this.zoom = 0.78;
                    cx.notify();
                  },
                })
              )
              .child(
                ghostBtn("obs-gr-zin", "+", t, {
                  onClick: (_e, cx) => {
                    this.zoom = Math.min(2.0, this.zoom * 1.15);
                    cx.notify();
                  },
                })
              )
          )
      )
      .child(
        div()
          .id("obs-graph-viewport")
          .flex_1()
          .w_full()
          .h_full()
          .min_h(0)
          .relative()
          .overflow_hidden()
          .bg(t.background)
          .cursor_grab()
          .on_mouse_down("left", (e, cx) => {
            this.drag = {
              startX: e.position.x,
              startY: e.position.y,
              origPanX: this.panX,
              origPanY: this.panY,
            };
            cx.notify();
          })
          .on_mouse_move((e, cx) => {
            if (!this.drag) return;
            this.panX = this.drag.origPanX + (e.position.x - this.drag.startX);
            this.panY = this.drag.origPanY + (e.position.y - this.drag.startY);
            cx.notify();
          })
          .on_mouse_up("left", (_e, cx) => {
            this.drag = null;
            cx.notify();
          })
          .on_scroll_wheel((e, cx) => {
            const dx = e.delta?.x || 0;
            const dy = e.delta?.y || 0;
            if (e.modifiers?.control) {
              this.zoom = Math.max(0.28, Math.min(2.0, this.zoom * (dy < 0 ? 1.1 : 0.9)));
            } else {
              this.panX += dx * 18;
              this.panY += dy * 18;
            }
            cx.notify();
          })
          .when(Boolean(hasSvg), (el) =>
            el.child(
              div()
                .absolute()
                .left(svgLeft)
                .top(svgTop)
                .w(svgW)
                .h(svgH)
                .child(image(`data/obsidian-cache/${gr.svg_cache_name}`).w(svgW).h(svgH))
            )
          )
          .children(
            nodes.map((nd, idx) => {
              const cardScale = Math.max(0.74, Math.min(1.15, scale));
              const cardW = Math.round((nd.is_center ? 192 : 148) * cardScale);
              const cardH = Math.round((nd.is_center ? 46 : 38) * cardScale);
              const x = Math.round(centerX + nd.x * scale - cardW / 2);
              const y = Math.round(centerY + nd.y * scale - cardH / 2);
              const shortTitle = String(nd.title || "")
                .replace(/^(?:L[0-3]|0[0-9])\s*[—–-]\s*/i, "")
                .replace(/^Role\s+MOC\s*[—–-]\s*/i, "")
                .replace(/\s*Map-Of-Content\s*\(MOC\)/i, "");

              return v_flex()
                .id(`obs-gr-nd-${idx}`)
                .absolute()
                .left(x)
                .top(y)
                .w(cardW)
                .h(cardH)
                .px(7)
                .py(4)
                .gap(1)
                .rounded(6)
                .cursor_pointer()
                .bg(nd.is_center ? t.selected : nd.fill || t.surface)
                .border_1()
                .border_color(nd.is_center ? t.accent : nd.border || t.border)
                .hover((s) => s.bg(t.hover).border_color(nd.color || t.accent))
                .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
                .on_click((_e, cx) => {
                  this.activeNotePath = nd.relpath;
                  this.refresh(cx);
                })
                .child(
                  h_flex()
                    .w_full()
                    .gap(4)
                    .items_center()
                    .when(nd.level !== null && nd.level !== undefined, (r) =>
                      r.child(
                        div()
                          .flex_none()
                          .text_size(9.5)
                          .font_semibold()
                          .text_color(nd.color || levelTint(nd.level, t))
                          .child(`L${nd.level}`)
                      )
                    )
                    .child(
                      div()
                        .flex_1()
                        .min_w(0)
                        .truncate()
                        .font_medium()
                        .text_size(10.5)
                        .text_color(t.foreground)
                        .child(shortTitle)
                    )
                )
                .child(
                  h_flex()
                    .w_full()
                    .justify_between()
                    .items_center()
                    .child(
                      div()
                        .text_size(9.5)
                        .text_color(t.dim)
                        .child(`← ${nd.in_degree}  ·  → ${nd.out_degree}`)
                    )
                    .when(Boolean(nd.is_center), (r) =>
                      r.child(
                        div()
                          .id("obs-gr-open-doc")
                          .text_size(9.5)
                          .font_medium()
                          .text_color(t.accent)
                          .on_click((_e, cx) => this.openNote(nd.relpath, cx, { pushHistory: true }))
                          .child("Read →")
                      )
                    )
                );
            })
          )
      );
  }

  renderCanvasView(t) {
    const cv = this.state?.canvas;
    const allCanvases = this.state?.canvases || [];
    if (!cv) {
      return v_flex()
        .flex_1()
        .w_full()
        .h_full()
        .items_center()
        .justify_center()
        .child(div().text_color(t.muted).child("No .canvas maps found in vault"));
    }

    const bounds = cv.bounds || {
      min_x: 0,
      min_y: 0,
      width: 2000,
      height: 1200,
      vb_x: -60,
      vb_y: -60,
      vb_w: 2120,
      vb_h: 1320,
    };
    const scale = this.zoom;
    const offsetX = 48 - bounds.min_x * scale + this.panX;
    const offsetY = 42 - bounds.min_y * scale + this.panY;

    const svgLeft = Math.round(offsetX + (bounds.vb_x ?? bounds.min_x - 60) * scale);
    const svgTop = Math.round(offsetY + (bounds.vb_y ?? bounds.min_y - 60) * scale);
    const svgW = Math.max(100, Math.round((bounds.vb_w || bounds.width + 120) * scale));
    const svgH = Math.max(100, Math.round((bounds.vb_h || bounds.height + 120) * scale));
    const hasSvg = cv.svg_cache_name && this.cachedAssets.has(cv.svg_cache_name);

    return v_flex()
      .flex_1()
      .w_full()
      .h_full()
      .min_w(0)
      .min_h(0)
      .child(
        h_flex()
          .h(32)
          .w_full()
          .flex_none()
          .px(10)
          .gap(6)
          .items_center()
          .justify_between()
          .bg(t.surface)
          .border_b(1)
          .border_color(t.border)
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .children(
                allCanvases.map((cPath, idx) => {
                  const shortName = String(cPath)
                    .split("/")
                    .pop()
                    .replace(/\.canvas$/i, "")
                    .replace(/^\d+\s*-\s*/, "");
                  return ghostBtn(
                    `obs-cv-pick-${idx}`,
                    shortName.length > 26 ? shortName.slice(0, 26) + "…" : shortName,
                    t,
                    {
                      active: cPath === cv.relpath,
                      onClick: (_e, cx) => {
                        this.activeCanvasPath = cPath;
                        this.panX = 0;
                        this.panY = 0;
                        this.refresh(cx);
                      },
                    }
                  );
                })
              )
          )
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(
                ghostBtn("obs-cv-zout", "−", t, {
                  onClick: (_e, cx) => {
                    this.zoom = Math.max(0.25, this.zoom / 1.15);
                    cx.notify();
                  },
                })
              )
              .child(
                ghostBtn("obs-cv-zreset", `${Math.round(this.zoom * 100)}%`, t, {
                  onClick: (_e, cx) => {
                    this.panX = 0;
                    this.panY = 0;
                    this.zoom = 0.65;
                    cx.notify();
                  },
                })
              )
              .child(
                ghostBtn("obs-cv-zin", "+", t, {
                  onClick: (_e, cx) => {
                    this.zoom = Math.min(1.8, this.zoom * 1.15);
                    cx.notify();
                  },
                })
              )
          )
      )
      .child(
        div()
          .id("obs-canvas-viewport")
          .flex_1()
          .w_full()
          .h_full()
          .min_h(0)
          .relative()
          .overflow_hidden()
          .bg(t.background)
          .cursor_grab()
          .on_mouse_down("left", (e, cx) => {
            this.drag = {
              startX: e.position.x,
              startY: e.position.y,
              origPanX: this.panX,
              origPanY: this.panY,
            };
            cx.notify();
          })
          .on_mouse_move((e, cx) => {
            if (!this.drag) return;
            this.panX = this.drag.origPanX + (e.position.x - this.drag.startX);
            this.panY = this.drag.origPanY + (e.position.y - this.drag.startY);
            cx.notify();
          })
          .on_mouse_up("left", (_e, cx) => {
            this.drag = null;
            cx.notify();
          })
          .on_scroll_wheel((e, cx) => {
            const dx = e.delta?.x || 0;
            const dy = e.delta?.y || 0;
            if (e.modifiers?.control) {
              this.zoom = Math.max(0.25, Math.min(1.8, this.zoom * (dy < 0 ? 1.1 : 0.9)));
            } else {
              this.panX += dx * 18;
              this.panY += dy * 18;
            }
            cx.notify();
          })
          .when(Boolean(hasSvg), (el) =>
            el.child(
              div()
                .absolute()
                .left(svgLeft)
                .top(svgTop)
                .w(svgW)
                .h(svgH)
                .child(image(`data/obsidian-cache/${cv.svg_cache_name}`).w(svgW).h(svgH))
            )
          )
          .children(
            (cv.nodes || []).map((nd, idx) => {
              const x = Math.round(offsetX + nd.x * scale);
              const y = Math.round(offsetY + nd.y * scale);
              const w = Math.max(80, Math.round(nd.width * scale));
              const h = Math.max(44, Math.round(nd.height * scale));
              const tone = CANVAS_SURFACE_MAP[nd.color] || {
                border: t.border,
                fill: t.surface,
                accent: levelTint(nd.level, t),
              };

              if (nd.type === "group") {
                return v_flex()
                  .id(`obs-cv-grp-${idx}`)
                  .absolute()
                  .left(x)
                  .top(y)
                  .w(w)
                  .h(h)
                  .rounded(8)
                  .border_1()
                  .border_color(tone.border)
                  .bg(t.background)
                  .child(
                    h_flex()
                      .w_full()
                      .px(8)
                      .py(4)
                      .gap(6)
                      .items_center()
                      .bg(tone.fill)
                      .border_b(1)
                      .border_color(tone.border)
                      .child(div().w(6).h(6).rounded_full().bg(tone.accent))
                      .child(
                        div()
                          .font_semibold()
                          .text_size(11)
                          .text_color(t.foreground)
                          .truncate()
                          .child(String(nd.title || "Group"))
                      )
                  );
              }

              return v_flex()
                .id(`obs-cv-node-${idx}`)
                .absolute()
                .left(x)
                .top(y)
                .w(w)
                .h(h)
                .p(8)
                .gap(4)
                .rounded(6)
                .overflow_hidden()
                .cursor_pointer()
                .bg(tone.fill)
                .border_1()
                .border_color(tone.border)
                .hover((s) => s.bg(t.hover).border_color(tone.accent))
                .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
                .on_click((_e, cx) => {
                  if (nd.file) {
                    this.openNote(nd.file, cx, { pushHistory: true });
                  }
                })
                .child(
                  h_flex()
                    .w_full()
                    .gap(5)
                    .items_center()
                    .when(nd.level !== null && nd.level !== undefined, (r) =>
                      r.child(
                        div()
                          .flex_none()
                          .text_size(9.5)
                          .font_semibold()
                          .text_color(tone.accent)
                          .child(`L${nd.level}`)
                      )
                    )
                    .child(
                      div()
                        .flex_1()
                        .min_w(0)
                        .truncate()
                        .font_medium()
                        .text_size(11.5)
                        .text_color(t.foreground)
                        .child(String(nd.title || nd.file || "Card"))
                    )
                )
                .when(Boolean(nd.excerpt) && h >= 68, (el) =>
                  el.child(
                    div()
                      .w_full()
                      .text_size(10.5)
                      .text_color(t.muted)
                      .child(String(nd.excerpt || ""))
                  )
                );
            })
          )
      );
  }

  renderTicketBriefView(t) {
    const tb = this.state?.ticket_brief;
    if (!tb) {
      return v_flex()
        .flex_1()
        .w_full()
        .h_full()
        .items_center()
        .justify_center()
        .child(div().text_color(t.muted).child("Resolving Kanban Linked-Knowledge Brief…"));
    }

    const sections = (tb.sections || []).filter((s) => s.items && s.items.length > 0);
    const deliverables = tb.deliverables || [];
    const skills = tb.skills || [];

    return v_flex()
      .id("obs-ticket-scroll")
      .flex_1()
      .w_full()
      .h_full()
      .min_w(0)
      .min_h(0)
      .overflow_y_scrollbar()
      .px(24)
      .py(20)
      .gap(16)
      .child(
        v_flex()
          .w_full()
          .flex_none()
          .pb(14)
          .gap(8)
          .border_b(1)
          .border_color(t.border)
          .child(
            h_flex()
              .w_full()
              .justify_between()
              .items_center()
              .child(
                h_flex()
                  .gap(8)
                  .items_center()
                  .child(
                    div()
                      .text_size(11.5)
                      .font_semibold()
                      .text_color(t.accent)
                      .child(String(tb.ticket_id || "Workspace"))
                  )
                  .when(skills.length > 0, (el) =>
                    el.child(
                      div()
                        .text_size(11)
                        .text_color(t.dim)
                        .child(`Skills: ${skills.slice(0, 5).join(", ")}`)
                    )
                  )
              )
              .child(
                ghostBtn("obs-open-kanban", "Open Kanban Board ↗", t, {
                  active: true,
                  onClick: () => run("pane.split", { direction: "right", mod: "herdr-kanban" }),
                })
              )
          )
          .child(
            div()
              .w_full()
              .font_semibold()
              .text_size(17)
              .text_color(t.foreground)
              .child(String(tb.title || "Linked-Knowledge Brief"))
          )
          .when(deliverables.length > 0, (el) =>
            el.child(
              v_flex()
                .w_full()
                .pt(4)
                .gap(3)
                .children(
                  deliverables.map((d) =>
                    div()
                      .w_full()
                      .text_size(11.5)
                      .text_color(t.muted)
                      .child(`• ${d}`)
                  )
                )
            )
          )
      )
      .children(
        sections.map((sec) =>
          v_flex()
            .w_full()
            .flex_none()
            .gap(6)
            .child(
              div()
                .font_semibold()
                .text_size(12.5)
                .text_color(t.foreground)
                .child(`${sec.title} (${sec.items.length})`)
            )
            .children(
              sec.items.map((item, idx) =>
                v_flex()
                  .id(`obs-tb-${sec.id}-${idx}`)
                  .w_full()
                  .flex_none()
                  .px(12)
                  .py(8)
                  .gap(3)
                  .rounded(6)
                  .cursor_pointer()
                  .bg(t.surface)
                  .border_1()
                  .border_color(t.border)
                  .hover((s) => s.bg(t.hover))
                  .on_click((_e, cx) => this.openNote(item.relpath, cx, { pushHistory: true }))
                  .child(
                    h_flex()
                      .w_full()
                      .gap(6)
                      .items_center()
                      .when(item.level !== null && item.level !== undefined, (r) =>
                        r.child(
                          div()
                            .flex_none()
                            .text_size(10)
                            .font_semibold()
                            .text_color(levelTint(item.level, t))
                            .child(`L${item.level}`)
                        )
                      )
                      .child(
                        div()
                          .flex_1()
                          .min_w(0)
                          .truncate()
                          .font_medium()
                          .text_size(12)
                          .text_color(t.foreground)
                          .child(String(item.title || ""))
                      )
                      .child(
                        div()
                          .flex_none()
                          .text_size(10.5)
                          .text_color(t.dim)
                          .child(String(item.relpath || ""))
                      )
                  )
                  .when(Boolean(item.excerpt), (c) =>
                    c.child(
                      div()
                        .w_full()
                        .truncate()
                        .text_size(11)
                        .text_color(t.muted)
                        .child(String(item.excerpt || ""))
                    )
                  )
              )
            )
        )
      );
  }

  renderLightbox(t) {
    const lb = this.lightbox || {};
    const overlayId = props()?.overlay;
    const availW = Math.max(320, (this.size?.width || 960) - 32);
    const availH = Math.max(220, (this.size?.height || 680) - 70);
    const natW = lb.width || 1600;
    const natH = lb.height || 640;
    const fitScale = Math.min(availW / Math.max(1, natW), availH / Math.max(1, natH));
    const baseW = Math.max(120, Math.round(natW * fitScale));
    const baseH = Math.max(80, Math.round(natH * fitScale));
    const drawW = Math.max(80, Math.round(baseW * this.lbZoom));
    const drawH = Math.max(60, Math.round(baseH * this.lbZoom));
    const centerX = Math.round((this.size?.width || 960) / 2 + this.lbPanX - drawW / 2);
    const centerY = Math.round(((this.size?.height || 680) - 38) / 2 + this.lbPanY - drawH / 2);

    return v_flex()
      .id("obs-lightbox-root")
      .size_full()
      .min_h(0)
      .overflow_hidden()
      .bg(t.background)
      .text_color(t.foreground)
      .text_size(12.5)
      .track_focus(this.handle)
      .on_size_change((size, cx) => {
        this.size = size;
        cx.notify();
      })
      .on_key_down((e, cx) => this.handleKeyDown(e, cx))
      .child(
        // Draggable floating window header (no stop_propagation on bar background so window drags)
        h_flex()
          .h(38)
          .w_full()
          .flex_none()
          .px(12)
          .gap(10)
          .items_center()
          .justify_between()
          .bg(t.chrome || t.surface)
          .border_b(1)
          .border_color(t.border)
          .child(
            h_flex()
              .gap(8)
              .items_center()
              .min_w(0)
              .child(
                div()
                  .flex_none()
                  .text_size(10.5)
                  .font_semibold()
                  .text_color(t.accent)
                  .child(String(lb.format || "FIGURE").toUpperCase())
              )
              .child(
                div()
                  .truncate()
                  .font_medium()
                  .text_size(12.5)
                  .text_color(t.foreground)
                  .child(String(lb.title || "Expanded Figure"))
              )
              .child(
                div()
                  .flex_none()
                  .text_size(11)
                  .text_color(t.dim)
                  .child(`${natW} × ${natH}  ·  Drag header to move`)
              )
          )
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .flex_none()
              .child(
                ghostBtn("obs-lb-zout", "−", t, {
                  onClick: (_e, cx) => {
                    this.lbZoom = Math.max(0.25, this.lbZoom / 1.2);
                    cx.notify();
                  },
                })
              )
              .child(
                ghostBtn("obs-lb-zfit", `${Math.round(this.lbZoom * 100)}%`, t, {
                  onClick: (_e, cx) => {
                    this.lbZoom = 1.0;
                    this.lbPanX = 0;
                    this.lbPanY = 0;
                    cx.notify();
                  },
                })
              )
              .child(
                ghostBtn("obs-lb-zin", "+", t, {
                  onClick: (_e, cx) => {
                    this.lbZoom = Math.min(4.5, this.lbZoom * 1.2);
                    cx.notify();
                  },
                })
              )
              .when(Boolean(lb.source), (el) =>
                el.child(
                  ghostBtn("obs-lb-src", this.lbShowSource ? "Diagram" : "Source", t, {
                    active: this.lbShowSource,
                    onClick: (_e, cx) => {
                      this.lbShowSource = !this.lbShowSource;
                      cx.notify();
                    },
                  })
                )
              )
              .child(
                ghostBtn(
                  "obs-lb-mode",
                  this.lightboxKind === "window" ? "Modal ⤢" : "Float ❐",
                  t,
                  {
                    onClick: (_e, cx) => {
                      const nextKind = this.lightboxKind === "window" ? "dialog" : "window";
                      if (overlayId) closeOverlay(overlayId);
                      this.openFigureFloat(lb, cx, nextKind);
                    },
                  }
                )
              )
              .child(
                ghostBtn("obs-lb-close", "Close ×", t, {
                  primary: true,
                  onClick: () => {
                    if (overlayId) closeOverlay(overlayId);
                  },
                })
              )
          )
      )
      .child(
        this.lbShowSource && lb.source
          ? v_flex()
              .id("obs-lb-src-scroll")
              .flex_1()
              .w_full()
              .h_full()
              .min_h(0)
              .overflow_y_scrollbar()
              .p(16)
              .bg(t.background)
              .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
              .child(
                div()
                  .w_full()
                  .flex_none()
                  .child(
                    TextView.markdown(
                      "obs-lb-src-md",
                      `\`\`\`${lb.format || "mermaid"}\n${lb.source}\n\`\`\``
                    ).selectable(true)
                  )
              )
          : div()
              .id("obs-lb-viewport")
              .flex_1()
              .w_full()
              .h_full()
              .min_h(0)
              .relative()
              .overflow_hidden()
              .bg(t.background)
              .cursor_grab()
              .on_mouse_down("left", (e, cx) => {
                cx.stop_propagation();
                this.lbDrag = {
                  startX: e.position.x,
                  startY: e.position.y,
                  origPanX: this.lbPanX,
                  origPanY: this.lbPanY,
                };
                cx.notify();
              })
              .on_mouse_move((e, cx) => {
                if (!this.lbDrag) return;
                this.lbPanX = this.lbDrag.origPanX + (e.position.x - this.lbDrag.startX);
                this.lbPanY = this.lbDrag.origPanY + (e.position.y - this.lbDrag.startY);
                cx.notify();
              })
              .on_mouse_up("left", (_e, cx) => {
                this.lbDrag = null;
                cx.notify();
              })
              .on_scroll_wheel((e, cx) => {
                const dy = e.delta?.y || 0;
                if (dy !== 0) {
                  this.lbZoom = Math.max(0.25, Math.min(4.5, this.lbZoom * (dy < 0 ? 1.12 : 0.89)));
                  cx.notify();
                }
              })
              .child(
                this.lbReady && lb.cacheName
                  ? div()
                      .absolute()
                      .left(centerX)
                      .top(centerY)
                      .w(drawW)
                      .h(drawH)
                      .child(image(`data/obsidian-cache/${lb.cacheName}`).w(drawW).h(drawH))
                  : v_flex()
                      .size_full()
                      .items_center()
                      .justify_center()
                      .child(
                        div()
                          .text_size(12)
                          .text_color(t.muted)
                          .child("Rendering high-resolution figure…")
                      )
              )
      );
  }

  render(cx) {
    const t = theme();
    if (this.isLightbox) {
      return this.renderLightbox(t);
    }
    if (!checking()) {
      const navUpdated = this.consumeSharedNav();
      const curTarget = resolveWorkspaceTarget(this.lastTarget);
      const curTargetKey = `${curTarget.on || "local"}:${curTarget.spaceId || ""}:${curTarget.cwd || ""}`;
      if (curTargetKey !== this.lastTargetKey || navUpdated) {
        if (
          this.lastTarget?.spaceId &&
          curTarget.spaceId &&
          this.lastTarget.spaceId !== curTarget.spaceId &&
          !navUpdated
        ) {
          this.activeNotePath = null;
          this.activeCanvasPath = null;
          this.activeTicket = null;
        }
        this.lastTargetKey = curTargetKey;
        this.refresh(cx, { forceSync: navUpdated });
      }
    }
    const noVault = Boolean(this.state && this.state.has_vault === false);
    return v_flex()
      .id("root")
      .size_full()
      .min_h(0)
      .overflow_hidden()
      .bg(t.background)
      .text_color(t.foreground)
      .text_size(12.5)
      .track_focus(this.handle)
      .on_size_change((size, cx) => {
        const wDiff = Math.abs((this.size?.width || 0) - size.width);
        const hDiff = Math.abs((this.size?.height || 0) - size.height);
        this.size = size;
        if ((wDiff > 24 || hDiff > 24) && this.viewMode === "treemap") {
          this.refresh(cx, { background: true });
        } else {
          cx.notify();
        }
      })
      .on_key_down((e, cx) => this.handleKeyDown(e, cx))
      .child(this.renderHeader(t))
      .when(Boolean(this.error), (el) =>
        el.child(
          div()
            .w_full()
            .flex_none()
            .px(12)
            .py(6)
            .bg(t.blocked || t.ansi1)
            .text_size(11.5)
            .text_color("#ffffff")
            .child(String(this.error || ""))
        )
      )
      .when(noVault, (el) =>
        el.child(
          v_flex()
            .flex_1()
            .w_full()
            .h_full()
            .items_center()
            .justify_center()
            .gap(6)
            .child(
              div()
                .text_size(12.5)
                .font_medium()
                .text_color(t.muted)
                .child("No Obsidian Vault in this space")
            )
            .child(
              div()
                .text_size(11)
                .text_color(t.dim)
                .child("Switch to a workspace with an .obsidian or docs/.obsidian directory")
            )
        )
      )
      .when(!noVault, (el) =>
        el.child(
          h_flex()
            .flex_1()
            .w_full()
            .h_full()
            .min_w(0)
            .min_h(0)
            .when(Boolean(this.sidebarOpen), (el) => el.child(this.renderLeftSidebar(t)))
            .when(this.viewMode === "note", (el) => el.child(this.renderNoteView(t)))
            .when(this.viewMode === "treemap", (el) => el.child(this.renderTreemapView(t)))
            .when(this.viewMode === "graph", (el) => el.child(this.renderGraphView(t)))
            .when(this.viewMode === "canvas", (el) => el.child(this.renderCanvasView(t)))
            .when(this.viewMode === "ticket", (el) => el.child(this.renderTicketBriefView(t)))
        )
      );
  }
}
