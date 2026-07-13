// ブラウザ playground 用の公開 API（docs/ailex.js にバンドルされる）
export { parseProgram, check, runContracts, evalInProgram, showExpr, showProgram, valEq } from "./lang.ts";
export { toJs, runJs } from "./tojs.ts";
