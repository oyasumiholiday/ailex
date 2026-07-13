// ailex/.env があれば読み込む（KEY=VALUE 形式・# コメント可）。
// 既に環境変数が設定されていればそちらを優先する。
// これにより「ターミナルで export した鍵がエージェントのシェルに届かない」問題を回避できる。
// ⚠ ailex/.env は秘密情報。共有・コミットしないこと（.gitignore 済み）。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

try {
  const here = dirname(fileURLToPath(import.meta.url));
  const text = readFileSync(join(here, ".env"), "utf8");
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!m || m[1].startsWith("#")) continue;
    const [, k, raw] = m;
    const v = raw.replace(/^["']|["']$/g, "");
    if (!process.env[k]) process.env[k] = v;
  }
} catch {
  // .env が無ければ何もしない（環境変数だけで動く）
}
