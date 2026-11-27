import { useTranslation } from "react-i18next";
const copy = {
  newChat: ["New chat", "新建聊天", "新增聊天"],
  useInChat:['Use in chat','在聊天中使用','在聊天中使用'],
  toolPrompt:['Help me with: ','帮我处理：','幫我處理：'],
  search: ["Search chats…", "搜索聊天…", "搜尋聊天…"],
  data: ["Data repository", "数据仓库", "資料倉庫"],
  upload: ['Upload data', '上传数据', '上傳資料'],
  files: ['File library','文件库','檔案庫'],
  system: ['System administration','系统管理','系統管理'],
  language: ['Interface language','界面语言','介面語言'],
  tools: ["Tools", "工具", "工具"],
  abilities: ["Assistant abilities", "助手能力", "助手能力"],
  chats: ["Chats", "聊天", "聊天"],
  progress: ["Background progress", "后台进度", "背景進度"],
  account: ["Account & settings", "账号与设置", "帳戶與設定"],
  newFolder: ["New folder", "新建文件夹", "新增資料夾"],
  folderName: ["Folder name", "文件夹名称", "資料夾名稱"],
  rename: ["Rename", "重命名", "重新命名"],
  removeFolder: ["Delete folder", "删除文件夹", "刪除資料夾"],
  folderHint: [
    "Chats will be kept outside the folder.",
    "聊天会保留并移回外层。",
    "聊天將保留並移回外層。",
  ],
  move: ["Move to folder", "移至文件夹", "移至資料夾"],
  outside: ["Outside folders", "移出文件夹", "移出資料夾"],
  unfiled: ['Other chats','其他聊天','其他聊天'],
  pin: ["Pin", "置顶", "置頂"],
  unpin: ["Unpin", "取消置顶", "取消置頂"],
  pinned: ["Pinned", "置顶", "置頂"],
  today: ["Today", "今天", "今天"],
  yesterday: ["Yesterday", "昨天", "昨天"],
  earlier: ["Earlier", "更早", "較早"],
  more: ["Load more", "加载更多", "載入更多"],
  empty: ["No chats here yet", "这里还没有聊天", "這裡還沒有聊天"],
  noResults: ["No matching chats", "没有匹配的聊天", "沒有符合的聊天"],
  save: ["Save", "保存", "儲存"],
  cancel: ["Cancel", "取消", "取消"],
  delete: ["Delete chat", "删除聊天", "刪除聊天"],
  deleteFailed: [
    "Could not delete this chat. It has been restored in the list; please try again.",
    "未能删除此对话，已恢复到列表，请重试。",
    "未能刪除此對話，已還原至列表，請重試。",
  ],
  deleteHint: [
    "Delete this chat and its associated files?",
    "删除此聊天及其关联文件？",
    "刪除此聊天及其關聯檔案？",
  ],
  export: ["Export chat", "导出聊天", "匯出聊天"],
  menu: ["Chat options", "聊天选项", "聊天選項"],
  folderMenu: ["Folder options", "文件夹选项", "資料夾選項"],
  close: ["Close sidebar", "关闭侧边栏", "關閉側邊欄"],
  open: ["Open sidebar", "打开侧边栏", "開啟側邊欄"],
  loading: ["Loading…", "加载中…", "載入中…"],
  running: ["Working", "处理中", "處理中"],
  queued: ["Waiting", "等待中", "等待中"],
  blocked: ["Needs your attention", "需要你处理", "需要你處理"],
  paused: ["Paused", "已暂停", "已暫停"],
  failed: ["Failed", "处理失败", "處理失敗"],
  records: ["Run records", "执行记录", "執行記錄"],
  backToTools: ['Back to tools', '返回工具', '返回工具'],
  recordsHint: [
    "Review computations, models and results.",
    "查看计算、模型和结果记录。",
    "查看運算、模型及結果紀錄。",
  ],
} as const;
export function useSidebarText() {
  const { i18n } = useTranslation();
  const index = i18n.language.startsWith("zh")
    ? /HK|TW|Hant/i.test(i18n.language)
      ? 2
      : 1
    : 0;
  return (key: keyof typeof copy) => copy[key][index];
}
