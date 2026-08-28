// 测试环境无 @types/node（阶段 6 不新增依赖）。
// 这里为测试文件中用到的最小 Node API 提供 ambient 声明，仅类型层面生效。
declare module "node:fs" {
  export function readFileSync(pathname: string, encoding: string): string;
}

declare module "node:path" {
  const pathModule: { join: (...segments: string[]) => string };
  export default pathModule;
}

declare const process: { cwd(): string };
