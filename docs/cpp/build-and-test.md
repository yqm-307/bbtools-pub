# C++ 构建与测试约定（bbtools 家族）

**所属**：pub `docs/cpp/`，bbtools 家族特有取值；构建与格式的通用判断见 `third-party/bbt-agent-toolkit/standards/cpp/format.md`，测试方法与执行的通用规则见 `third-party/bbt-agent-toolkit/agents/qa/`，本文只写 bbtools 家族的 C++ 文件、目标、标签与命令约定。

## 1 构建与格式

- 格式细则真源：pub 仓库根目录的 `.clang-format`（已用 clang-format 23.1.3 验证；消费仓按已固定工具版本核对后采用，不自动覆盖现有配置），带文档注释的成员之间的空行 clang-format 无法强制，靠人工或提交前检查。`.editorconfig` 负责 UTF-8/LF 等文本约定。按项目格式检查改动行，不因功能改动顺手清洗全仓。
- 新模块、示例和测试必须接入真实 CMake 目标；不引入新 warning。固定已验收的跨仓版本，依赖或构建门禁失败时不能改用更底层命令绕过保护。
- CI workflow 只编排，执行逻辑放在仓库已有的 `scripts/ci/`；CI 修改和系统安装不属于普通 C++ 改动的默认权限。

正例：先使用目标工程的 CMake 配置和 pin，再运行聚焦 target/CTest；配置失败就记录为配置失败。

反例：CMake 因依赖 pin 拒绝后，手抄 build.ninja 的编译参数直接调用编译器，然后把它说成完整构建通过。

## 2 测试接入

- 沿用项目已选测试框架；测试源通常位于 `tests/<module>/Test_<行为>.cc`，每个可独立构建为目标，CTest 名称按模块和行为注册。
- 按实际性质标记 `smoke`、`unit`、`integration`、`live`、`perf`，不把标签当作证据本身。CTest 名以模块为前缀时，标签和名称过滤同时生效，开发中可用 `ctest --test-dir build -L smoke -R '^<module>\.'` 只选某个模块的冒烟。
- 检查构建开关、CTest 注册集和 CI 执行路径；空过滤、缺失二进制、`Not Run` 或被管道吞掉的失败都不能算通过。用例怎么设计、何时运行按 `third-party/bbt-agent-toolkit/agents/qa/`，本节只定义 C++ 文件、目标和注册约定。

## 3 复杂度工具

Review C++ 实现、接口或抽象变化时，可用 pub 的复杂度打分器作辅助参考，只作参考、不作门禁；用法与评审者边界见 [tools/complexity/README.md](../../tools/complexity/README.md)「在 Review 中使用」。

**做到什么程度算够**：新代码遵守仓库真实编译约定，所有权与线程边界可解释，公共头没有无意泄漏，依赖门禁没有被绕过，测试目标真实注册且验证范围写清。
