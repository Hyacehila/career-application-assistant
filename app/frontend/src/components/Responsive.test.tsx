import { readFileSync } from "node:fs";
import path from "node:path";


import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRecord, ApplicationDetail } from "../api/client";
import { makeEvent, makeRecord } from "../test/fixtures";
import { jsonBody, okBody, STANDARD_HEALTH } from "../test/http";
import App from "../App";
import BoardView from "./BoardView";
import DetailDrawer from "./DetailDrawer";
import TableView from "./TableView";
import type { BoardGroup } from "../lib/statuses";

type MatchMediaMockFn = (query: string) => {
  matches: boolean;
  media?: string;
  onchange?: null;
  addEventListener?: (type: string, listener: () => void) => void;
  removeEventListener?: (type: string, listener: () => void) => void;
  addListener?: (listener: () => void) => void;
  removeListener?: (listener: () => void) => void;
  dispatchEvent?: (event?: unknown) => boolean;
};

declare global {
  // eslint-disable-next-line no-var
  var __matchMediaMock: MatchMediaMockFn | undefined;
}

const STAGE_CHIPS: BoardGroup[] = [
  "pending_review",
  "applied",
  "assessment",
  "interview",
  "ended",
];

const baseCounts = {
  pending_review: 0,
  applied: 0,
  assessment: 0,
  interview: 0,
  ended: 0,
};

function mockMedia(mobile: boolean) {
  globalThis.__matchMediaMock = (query: string) => {
    const matches =
      query === "(max-width: 767px)"
        ? mobile
        : query === "(prefers-reduced-motion: reduce)"
          ? false
          : false;
    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: () => false,
    };
  };
}

function boardRecords(): ApplicationRecord[] {
  return [
    makeRecord({ id: 1, company_name: "示例科技", current_status: "pending_review" }),
    makeRecord({ id: 2, company_name: "示例网络", current_status: "applied" }),
    makeRecord({ id: 3, company_name: "示例云", current_status: "interview_1" }),
  ];
}

function boardProps(overrides: Partial<Parameters<typeof BoardView>[0]> = {}) {
  return {
    items: boardRecords(),
    loading: false,
    error: null,
    counts: { ...baseCounts, pending_review: 1, applied: 1, interview: 1 },
    stageGroup: "",
    selectedId: null,
    onOpen: () => {},
    onNewRecord: () => {},
    onRetry: () => {},
    onStatusChange: () => {},
    ...overrides,
  };
}

function detailFixture(record: ApplicationRecord): ApplicationDetail {
  return {
    application: record,
    events: [
      makeEvent({ id: 30, stage: "interview_1", event_date: "2026-08-25", scheduled_date: "2026-08-28", scheduled_time: "14:00", created_at: "2026-08-25T09:00:00+08:00" }),
      makeEvent({ id: 20, stage: "assessment", event_date: "2026-08-22", deadline_date: "2026-08-27", created_at: "2026-08-22T09:00:00+08:00" }),
      makeEvent({ id: 10, stage: "applied", event_date: "2026-08-20", created_at: "2026-08-20T09:00:00+08:00" }),
    ],
  };
}

const detailRecord = makeRecord({
  id: 42,
  company_name: "示例科技",
  job_title: "前端工程师",
  location: "上海",
  source: "官方网站",
  current_status: "interview_1",
  submitted_at: "2026-08-20T10:00:00+08:00",
  next_action: "准备一面",
  next_action_date: "2026-08-28",
});

function stubDetailFetch() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/events") || path.includes("DELETE")) return Promise.resolve(okBody({}));
    return Promise.resolve(jsonBody(detailFixture(detailRecord)));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubListFetch() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/health") return Promise.resolve(jsonBody(STANDARD_HEALTH));
    if (path.includes("/applications")) {
      return Promise.resolve(
        jsonBody({
          items: boardRecords(),
          total: 3,
          page: 1,
          page_size: 20,
          counts: { pending_review: 1, applied: 1, assessment: 0, interview: 1, ended: 0 },
          options: { types: ["校招"], cities: ["上海"], sources: ["官方网站"] },
        }),
      );
    }
    return Promise.resolve(okBody({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  globalThis.__matchMediaMock = undefined;
  vi.unstubAllGlobals();
  cleanup();
});

describe("响应式：窄屏（max-width 767px）", () => {
  it("看板渲染五个横向阶段选择器与单列列表，不再渲染五列 region", () => {
    mockMedia(true);
    render(<BoardView {...boardProps()} />);
    expect(screen.getByTestId("stage-chip-row")).toBeInTheDocument();
    STAGE_CHIPS.forEach((chip) => {
      expect(screen.getByTestId(`stage-chip-${chip}`)).toBeInTheDocument();
    });
    // 计数：chip 上显示对应分组计数（来自列表响应 counts）
    expect(screen.queryByTestId("stage-chip-all")).not.toBeInTheDocument();
    expect(screen.getByTestId("stage-chip-pending_review")).toHaveTextContent("1");
    expect(screen.getByTestId("stage-chip-applied")).toHaveTextContent("1");
    expect(screen.getByTestId("stage-chip-interview")).toHaveTextContent("1");
    expect(screen.getByTestId("stage-chip-ended")).toHaveTextContent("0");
    // 单列：stageGroup 为空时默认显示 pending_review 列
    expect(screen.getByRole("region", { name: "待确认投递" })).toHaveTextContent("示例科技");
    // 不再有五列 region
    expect(screen.queryByRole("region", { name: "已投递" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "笔试 / 测评" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "面试" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "已结束" })).not.toBeInTheDocument();
  });

  it("点击阶段 chip 调用 onStageGroupChange，且 chip 高度不小于 44px", async () => {
    const onStageGroupChange = vi.fn();
    mockMedia(true);
    render(<BoardView {...boardProps({ stageGroup: "applied", onStageGroupChange })} />);
    // jsdom 不计算布局（getBoundingClientRect/getComputedStyle 均为 0/空），
    // 触摸目标高度通过 CSS Modules 的静态声明断言：读取 BoardView.module.css，
    // 确认 .stageChip 规则块内声明 min-height: 44px。
    // vitest 的 import.meta.url 非 file 协议，使用项目根（测试以 pnpm --dir app/frontend test 运行）相对路径
    const css = readFileSync(path.join(process.cwd(), "src/components/BoardView.module.css"), "utf8");
    const chipRule = css
      .split(".stageChip {")
      .slice(1)
      .find((chunk: string) => chunk.includes("min-height"));
    expect(chipRule).toBeDefined();
    expect(chipRule!.split("}")[0]).toContain("min-height: 44px");
    const chip = screen.getByTestId("stage-chip-interview") as HTMLElement;
    // 当前 stageGroup 为 applied，对应 chip 处于选中态
    expect(screen.getByTestId("stage-chip-applied")).toHaveAttribute("aria-selected", "true");
    const user = userEvent.setup();
    await user.click(chip);
    expect(onStageGroupChange).toHaveBeenCalledWith("interview");
  });

  it("统一紧凑卡片在窄屏保留触控高度，并限制公司与岗位行数", () => {
    const css = readFileSync(path.join(process.cwd(), "src/components/BoardView.module.css"), "utf8");
    const cardRule = css.match(/\.card\s*\{([^}]*)\}/s)?.[1];
    const companyRule = css.match(/\.company\s*\{([^}]*)\}/s)?.[1];
    const jobRule = css.match(/\.job\s*\{([^}]*)\}/s)?.[1];
    const mobileCardRule = css.match(/\.mobileColumn \.card\s*\{([^}]*)\}/s)?.[1];

    expect(cardRule).toBeDefined();
    expect(cardRule).toContain("gap: 10px");
    expect(cardRule).toContain("min-height: 100px");
    expect(cardRule).toContain("padding: 13px 14px 12px");
    expect(companyRule).toContain("white-space: nowrap");
    expect(companyRule).toContain("text-overflow: ellipsis");
    expect(companyRule).toContain("overflow: hidden");
    expect(jobRule).toContain("-webkit-line-clamp: 2");
    expect(jobRule).toContain("-webkit-box-orient: vertical");
    expect(jobRule).toContain("overflow: hidden");
    expect(mobileCardRule).toContain("min-height: 96px");
    expect(mobileCardRule).not.toContain("grid-template-columns");
    expect(css).toContain("scrollbar-width: none");
  });

  it("表格渲染紧凑行：无九列 columnheader，保留行点击与分页条", async () => {
    mockMedia(true);
    const onOpen = vi.fn();
    render(
      <TableView
        items={boardRecords()}
        total={3}
        page={1}
        pageSize={20}
        loading={false}
        error={null}
        sort="updated_at"
        selectedId={2}
        onOpen={onOpen}
        onSortChange={() => {}}
        onPageChange={() => {}}
        onRetry={() => {}}
      />,
    );
    expect(screen.queryAllByRole("columnheader")).toHaveLength(0);
    const row = screen.getByTestId("table-row-1");
    expect(row).toHaveTextContent("示例科技");
    expect(row).toHaveTextContent("前端工程师");
    expect(row).toHaveTextContent("创建于 2026-08-20");
    // 选中态指示
    const selectedRow = screen.getByTestId("table-row-2");
    expect(selectedRow.className).toContain("mobileRowSelected");
    const user = userEvent.setup();
    await user.click(row);
    expect(onOpen).toHaveBeenCalledWith(1);
    // 保留分页条
    expect(screen.getByTestId("table-pagination-info")).toHaveTextContent("第 1 / 1 页 · 共 3 条");
  });

  it("DetailDrawer 渲染为底部面板，短时间线（最新 3 条）与更新状态/查看详情按钮", async () => {
    mockMedia(true);
    stubDetailFetch();
    render(
      <DetailDrawer
        recordId={42}
        record={detailRecord}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("drawer-bottom")).toBeInTheDocument();
    });
    // 底部面板 class 含 bottom
    const bottom = screen.getByTestId("drawer-bottom");
    expect(bottom.className).toContain("drawerBottom");
    // 当前进度
    expect(screen.getByTestId("drawer-current-status")).toHaveTextContent("1面");
    // 短时间线：3 条事件全部可见
    expect(screen.getByTestId("timeline-current")).toHaveTextContent("1面");
    expect(screen.getByText("2026-08-22")).toBeInTheDocument();
    expect(screen.getByText("2026-08-20")).toBeInTheDocument();
    // 下一步
    expect(screen.getByTestId("drawer-next-action")).toHaveTextContent("准备一面");
    // 按钮组：更新状态（主）与查看详情（次级，展开完整时间线）
    const updateUser = userEvent.setup();
    expect(screen.getByRole("button", { name: "更新状态" })).toBeInTheDocument();
    const expandButton = screen.getByTestId("drawer-expand-timeline");
    expect(expandButton).toHaveTextContent("查看详情");
  });

  it("底部抽屉 Esc 关闭", async () => {
    mockMedia(true);
    stubDetailFetch();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <DetailDrawer
        recordId={42}
        record={detailRecord}
        onClose={onClose}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("drawer-bottom")).toBeInTheDocument();
    });
    fireEvent.keyDown(document, { key: "Escape" });
    // 关闭动画 210ms 后调用 onClose（reduced-motion 时立即）
    await vi.waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });
});

describe("响应式：桌面（max-width 767px 不匹配）回归", () => {
  it("看板保持五列 region 与 dnd 目标，不渲染阶段 chip", () => {
    mockMedia(false);
    render(<BoardView {...boardProps()} />);
    expect(screen.queryByTestId("stage-chip-row")).not.toBeInTheDocument();
    ["待确认投递", "已投递", "笔试 / 测评", "面试", "已结束"].forEach((label) => {
      expect(screen.getByRole("region", { name: label })).toBeInTheDocument();
    });
    ["pending_review", "applied", "assessment", "interview", "ended"].forEach((group) => {
      expect(screen.getByTestId(`droppable-${group}`)).toBeInTheDocument();
    });
  });

  it("表格保持九列", () => {
    mockMedia(false);
    render(
      <TableView
        items={boardRecords()}
        total={3}
        page={1}
        pageSize={20}
        loading={false}
        error={null}
        sort="updated_at"
        selectedId={null}
        onOpen={() => {}}
        onSortChange={() => {}}
        onPageChange={() => {}}
        onRetry={() => {}}
      />,
    );
    const headers = screen.getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers).toEqual([
      "公司",
      "岗位",
      "类型",
      "地点",
      "当前阶段",
      "阶段日期",
      "投递日期",
      "来源",
      "更新时间",
    ]);
  });

  it("DetailDrawer 保持侧边面板", async () => {
    mockMedia(false);
    stubDetailFetch();
    render(
      <DetailDrawer
        recordId={42}
        record={detailRecord}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("drawer-side")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("drawer-bottom")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更多操作" })).toBeInTheDocument();
  });
});

describe("响应式：AppShell 窄屏顶栏与筛选折叠", () => {
  it("窄屏保留产品名/视图切换/搜索/新增，Filters 折叠进可展开的筛选区", async () => {
    mockMedia(true);
    stubListFetch();
    render(<App />);
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByTestId("mobile-filter-toggle")).toBeInTheDocument();
    });
    // 顶栏要素保留
    expect(screen.getByText("求职投递助手")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "看板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "表格" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("搜索公司或岗位")).toBeInTheDocument();
    expect(screen.getByTestId("new-record-button")).toBeInTheDocument();
    const shellCss = readFileSync(path.join(process.cwd(), "src/components/AppShell.module.css"), "utf8");
    const mobileRules = shellCss.split("@media (max-width: 767px)")[1];
    expect(mobileRules).toMatch(/\.viewButton\s*{[^}]*min-height:\s*44px/s);
    const tokensCss = readFileSync(path.join(process.cwd(), "src/styles/tokens.css"), "utf8");
    expect(tokensCss).toMatch(
      /@media \(max-width: 767px\)\s*{\s*\.overlayCardClose\s*{[^}]*width:\s*44px[^}]*height:\s*44px/s,
    );
    const filtersCss = readFileSync(path.join(process.cwd(), "src/components/Filters.module.css"), "utf8");
    const mobileFilterRules = filtersCss.split("@media (max-width: 767px)")[1];
    expect(mobileFilterRules).toMatch(/\.select\s*{[^}]*height:\s*44px/s);
    // 默认折叠：面板不可见
    expect(screen.queryByTestId("mobile-filter-panel")).not.toBeInTheDocument();
    // 展开后可见 type/city/source/sort（状态分组由横向阶段选择器承接，不在其中）
    await user.click(screen.getByTestId("mobile-filter-toggle"));
    const panel = await screen.findByTestId("mobile-filter-panel");
    expect(panel).toHaveTextContent("投递类型");
    expect(panel).toHaveTextContent("城市");
    expect(panel).toHaveTextContent("来源");
    expect(panel).toHaveTextContent("更新时间");
    expect(screen.getByTestId("mobile-filter-toggle")).toHaveAttribute("aria-expanded", "true");
  });

  it("窄屏看板视图显示横向阶段选择器并联动列表（chip 点击写 stageGroup）", async () => {
    mockMedia(true);
    stubListFetch();
    render(<App />);
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByTestId("stage-chip-row")).toBeInTheDocument();
    });
    // stageGroup 为空时默认 pending_review 列
    expect(screen.getByRole("region", { name: "待确认投递" })).toHaveTextContent("示例科技");
    await user.click(screen.getByTestId("stage-chip-applied"));
    await waitFor(() => {
      expect(screen.getByRole("region", { name: "已投递" })).toHaveTextContent("示例网络");
    });
    expect(window.location.search).toContain("stage_group=applied");
  });
});
