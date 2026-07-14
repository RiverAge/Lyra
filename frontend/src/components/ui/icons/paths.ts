/**
 * 图标 path data 集中表
 *
 * 风格：线性 stroke（lucide 同款审美），统一 24x24 viewBox
 * 所有路径源自 lucide-icons MIT 协议，裁剪为本项目实际所需子集
 * currentColor 继承文字色，stroke-width 默认 1.75
 *
 * 维护说明：增删图标在此增删键值，命名用 PascalCase
 */

export type IconName =
  | "Play"
  | "Pause"
  | "SkipBack"
  | "SkipForward"
  | "Volume2"
  | "VolumeX"
  | "ChevronLeft"
  | "ChevronRight"
  | "ChevronDown"
  | "RefreshCw"
  | "Search"
  | "Music"
  | "Music2"
  | "Check"
  | "X"
  | "AlertCircle"
  | "Loader2"
  | "ExternalLink"
  | "Save"
  | "Edit3"
  | "Trash2"
  | "ArrowLeft"
  | "Eye"
  | "Sun"
  | "Moon"
  | "Settings"
  | "Download"

/** 每个图标的内层 SVG 元素（path / circle / rect 等，不含外层 <svg>） */
export const iconPaths: Record<IconName, string> = {
  // ── 播放控制 ──
  Play: '<polygon points="6 3 20 12 6 21 6 3" fill="currentColor" stroke="none" />',
  Pause: '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none" /><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none" />',
  SkipBack: '<polygon points="19 20 9 12 19 4 19 20" fill="currentColor" stroke="none" /><line x1="5" y1="19" x2="5" y2="5" />',
  SkipForward: '<polygon points="5 4 15 12 5 20 5 4" fill="currentColor" stroke="none" /><line x1="19" y1="5" x2="19" y2="19" />',

  // ── 音量 ──
  Volume2: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor" stroke="none" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14" />',
  VolumeX: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor" stroke="none" /><line x1="22" y1="9" x2="16" y2="15" /><line x1="16" y1="9" x2="22" y2="15" />',

  // ── 方向 ──
  ChevronLeft: '<polyline points="15 18 9 12 15 6" />',
  ChevronRight: '<polyline points="9 18 15 12 9 6" />',
  ChevronDown: '<polyline points="6 9 12 15 18 9" />',
  ArrowLeft: '<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />',

  // ── 操作 ──
  RefreshCw: '<polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />',
  Search: '<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />',
  Download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />',
  Save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" />',
  Edit3: '<path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />',
  Trash2: '<polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" />',
  Eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />',
  ExternalLink: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />',
  Check: '<polyline points="20 6 9 17 4 12" />',
  X: '<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />',

  // ── 状态 ──
  AlertCircle: '<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />',
  Loader2: '<path d="M21 12a9 9 0 1 1-6.219-8.56" />',

  // ── 音乐 ──
  Music: '<path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />',
  Music2: '<path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />',

  // ── 主题/UI ──
  Sun: '<circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" /><line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" /><line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" /><line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />',
  Moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />',
  Settings: '<circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />',
}
