# Maya Python ツール ─ ホットアップデート実装ノート

Stylized Paint Projectile Tool の開発中に、「install.py を Maya にドラッグするだけで、以降 Maya を再起動せずに GitHub 最新版に更新できる」仕組みを作る過程で **踏んだ落とし穴** と **それを回避する実装パターン** をまとめた社内ナレッジ。次に同種のツール
(Maya 用のアーティスト向け Python ツール) を作るときに、同じ調査を繰り返さないための備忘録。

対象は Maya 2023 (Python 3.9) / Windows。Autodesk のドラッグ&ドロップ + シェルフ + GitHub 配布という構成を前提にしている。

---

## 0. 目指すゴール

エンドユーザー (アニメーター) から見た体験:

1. GitHub から `install.py` を落として Maya のビューポートにドラッグ → セットアップ完了
2. シェルフに追加されたボタンを押すと UI が起動
3. 開発者側で GitHub に修正を push した後は、**Maya 再起動なし** で UI 内の「Update」ボタン一発で最新版が反映される

このシンプルな体験に至るまでに 6 個以上の非自明な問題を踏んだ。以下はその全記録。

---

## 1. 失敗パターン (症状 → 原因 → 対策)

### 1-1. `cmds.circle(ch=False)` の戻り値が unpack エラー

**症状**
```
ValueError: not enough values to unpack (expected 2, got 1)
```

**原因**
`cmds.circle` は construction history あり (`ch=True`, デフォルト) だと `[transform, makeNurbCircle]` の 2 要素、`ch=False` だと `[transform]` の 1 要素しか返さない。

**対策**
history を切るなら unpack しない:
```python
ctrl = cmds.circle(n="ctrl", ch=False)[0]      # OK
# NG: ctrl, _ = cmds.circle(n="ctrl", ch=False)
```

**教訓**
Maya コマンドは同じ関数でもフラグ次第で戻り値の shape が変わる。`ch`, `q`, `e` 系フラグを付けたら戻り値を必ず docs で確認。

---

### 1-2. `shutil.copytree` がソースの mtime を保持してしまう

**症状**
`install.py` を再ドラッグしても、コピー先の `.py` の更新日時が変わらない。「上書きが効いていない」と誤診する。

**原因**
`shutil.copytree` は内部で `shutil.copy2` を使い、`copystat` でソースの mtime / atime / mode をコピー先に転写する。GitHub から `git clone` した .py はチェックアウト時刻の mtime を持つので、複数回コピーしても全部同じ mtime になる。

**対策**
mtime = 「install 実行時刻」にしたいなら、`copy2` を使わず自前で書き直す:

```python
def _atomic_copy_file(src, dst):
    with open(src, "rb") as fh:
        data = fh.read()
    _atomic_write_bytes(dst, data)   # mtime は書き込み時刻になる
```

**教訓**
`.py` のタイムスタンプは「本当に上書きされたか」を目視確認するデバッグ手掛かりになる。デフォルト挙動が copystat だと、その手掛かりが失われる。ツールの updater を書くときは自前 write を推奨。

---

### 1-3. Windows で read-only 属性のせいで `rmtree` / `os.replace` が失敗

**症状**
インストール自体は成功するが、次のインストール時にサイレントに失敗するケースがある (特にネットワークドライブや同期フォルダ)。

**原因**
Windows のファイル属性 read-only が付いていると、`shutil.rmtree` が `PermissionError` で止まる。`os.replace` も同じ。

**対策**
削除の前に必ず writable にする + `onerror` でリトライ:

```python
import stat

def _force_writable(path):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass

def _force_rmtree(path):
    def _on_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE); func(p)
        except Exception:
            pass
    for _ in range(3):
        try:
            shutil.rmtree(path, onerror=_on_error)
            if not os.path.exists(path): return
        except Exception:
            time.sleep(0.2)
    if os.path.exists(path):
        raise RuntimeError(f"cannot remove {path!r}")
```

**教訓**
Windows ではファイル操作に必ず retry ループを噛ませる。特に read-only + アンチウイルスがロックしているケース。

---

### 1-4. 書き込みが原子的でない → 半端ファイルが残る

**症状**
インストール途中でエラー → 中途半端な .py が残り、以降 import で SyntaxError

**対策**
一時ファイルに書いて `os.replace` で原子スワップ:

```python
def _atomic_write_bytes(target, data):
    if os.path.exists(target):
        _force_writable(target)
    tmp = target + ".tmp_install"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        try: os.fsync(fh.fileno())
        except Exception: pass
    os.replace(tmp, target)      # 同一ドライブ上なら atomic
```

**教訓**
「書き込み中にキャンセル」「ネットワーク断」「ディスクフル」があってもファイルが常に「以前の完全な状態」か「新しい完全な状態」のどちらかであることを保証する。

---

### 1-5. Python が `.py` を上書きしても古い `.pyc` を使い続ける

**症状**
`.py` を新しくしたのに、実行される内容が古い。

**原因**
Python は `__pycache__/*.pyc` にバイトコードキャッシュを持ち、`.py` の mtime と `.pyc` に記録された「元 .py の mtime」が一致していると `.pyc` を使う。**mtime が偶然一致すれば古い .pyc を使い続けてしまう**。

**対策**
インストール時に `__pycache__` フォルダを毎回消す:

```python
def _clean_pycache(pkg_dir):
    _force_rmtree(os.path.join(pkg_dir, "__pycache__"))
```

**教訓**
Python の pyc キャッシュは mtime ベースで、自前 updater を作ると壊れやすい。install の最後に必ず `__pycache__` を消す。

---

### 1-6. `sys.modules` にキャッシュされたモジュールが更新されない

**症状**
ファイルは新しくなったのに、import しても古いコードが走る。

**原因**
Python は 1 度 import したモジュールを `sys.modules` にキャッシュし、同じ名前の 2 回目以降の import は no-op。

**対策**
入れ替え前に強制フラッシュ:

```python
def _flush_imports(pkg="paint_projectile"):
    for name in list(sys.modules):
        if name == pkg or name.startswith(pkg + "."):
            sys.modules.pop(name, None)
```

シェルフボタンの起動コマンド側でも毎回フラッシュしておくと、次に開くとき必ず disk から最新を読む:

```python
_SHELF_CMD = """
import sys
for _m in [k for k in sys.modules
           if k == 'my_tool' or k.startswith('my_tool.')]:
    sys.modules.pop(_m, None)
import my_tool
my_tool.show()
"""
```

**教訓**
「ファイルは更新されているのにコードが変わらない」時の第 1 容疑者は `sys.modules`。第 2 容疑者は `__pycache__`。

---

### 1-7. GitHub raw の CDN が **query string を無視して** キャッシュする

**症状**
`?_={time.time()}` を付けて「cache busting しているつもり」でも、実行のたびに古いコンテンツが返ってくる。ダウンロードログは正常に見えるのに `previous: 0.1.7 → current: 0.1.7` のように更新されない。

**原因**
`raw.githubusercontent.com` の CDN (Varnish/Fastly) は **URL のパス部分のみを cache key にする**。`?_=1234` を付けても cache key に反映されないので、初回に取ったレスポンスが TTL 内 (数分〜数十分) は使い回される。ここでハマると発覚しにくい。`curl` で外から叩くと最新が返ってくるので余計に混乱する (別ネットワーク / 別 UA だと別 edge に当たる)。

**対策 (決定版)**
**Commit SHA を含んだ immutable URL を使う**。SHA-scoped URL は commit ごとに一意なので、CDN が何をキャッシュしていようが「新しい SHA = 別 URL = 別 cache key」となり必ず最新が取れる。

```python
import json, urllib.request

def _latest_sha():
    api = "https://api.github.com/repos/OWNER/REPO/branches/main"
    return json.loads(urllib.request.urlopen(api, timeout=30).read())["commit"]["sha"]

def download_file(rel_path):
    sha = _latest_sha()
    url = f"https://raw.githubusercontent.com/OWNER/REPO/{sha}/{rel_path}"
    return urllib.request.urlopen(url, timeout=30).read()
```

**教訓**
- ブランチ名 URL (`/main/path`) は CDN のキャッシュに引っかかる。
- クエリストリング cache-buster は raw.githubusercontent.com に対しては効かない。
- `Cache-Control: no-cache` ヘッダも同上、CDN によっては無視される。
- **一度は必ず SHA-pinned URL を使う** のがベストプラクティス。API コールが 1 回増えるコストは、キャッシュに悩まされるコストより遥かに小さい。

---

### 1-8. Maya のドラッグ&ドロップは **同じファイルを 2 回目にドラッグしても何も起こらない**

**症状**
`install.py` を初回ドラッグしたら install.py が動いた。修正を GitHub に push した後、もう一度同じ install.py をドラッグしても、ダイアログもログも出ず何も起こらない。Maya の再起動が必要になる。

**原因**
Maya の `onMayaDroppedPythonFile` フックは、同一セッション内で同じファイルパスに対して 1 度しか呼ばれない (モジュールキャッシュに拾われて no-op 化する)。

**対策**
ドラッグ&ドロップを「再アップデート手段」として使わない。代わりに以下を用意:

1. **ツール UI 内の「Update from GitHub」ボタン**
   ```python
   cmds.button(l="Update from GitHub", c=_update_from_github)
   ```
2. **シェルフボタンの右クリックポップアップメニュー**
   ```python
   btn = cmds.shelfButton(...)
   popup = cmds.popupMenu(parent=btn, button=3)  # 3 = right click
   cmds.menuItem(parent=popup, label="Launch",  command=LAUNCH_CMD)
   cmds.menuItem(parent=popup, label="Update",  command=UPDATE_CMD)
   ```

どちらも「URL を毎回 fetch → exec install.py → 再オープン」を叩き直せるので、drag の caching に依存しない。

**教訓**
「初回インストール」と「アップデート」は別導線で用意する。ドラッグ&ドロップは初回のみ、アップデートは UI ボタン or シェルフメニュー。

---

### 1-10. install.py の `_REMOTE_FILES` に新規モジュールを追加し忘れる

**症状**
新しい `.py` をパッケージに追加して push、ユーザーが Update を叩くと `ModuleNotFoundError: No module named '<pkg>.<newmodule>'`。

**原因**
install.py はダウンロード対象ファイルをハードコードした `_REMOTE_FILES` タプルで管理している。パッケージに新規ファイルを追加しても、ここに書かないとダウンロードされない。ローカルの `__init__.py` は新規モジュールを import しようとするが、ディスクには存在しないので失敗する。

**対策**
新規 `.py` を追加したら、必ず同じ commit で `install.py` の `_REMOTE_FILES` にも追記する。CI があるならインストール後 import 全モジュール可能かの smoke test を通すと確実。

**教訓**
「配布リストはコードの真実 (package structure) と乖離しやすい」。手動同期を義務にするか、自動列挙 (GitHub API tree walk 等) で解決。

---

### 1-9. コールバック内から親ウィンドウを消すと再オープン後に UI が出ない

**症状**
Update ボタンのハンドラで `cmds.deleteUI(WINDOW)` → 再インストール → `show()` を同期実行すると、install() の `confirmDialog` は表示されるが、その後の `show()` で開いたウィンドウが見えないか、そもそも作られない。

**原因**
- Update ボタンのコールバックが実行中に、そのボタンをホストしている親ウィンドウを削除している
- install() の中で `confirmDialog` がモーダル表示され、それが閉じた直後に `show()` が走るが、Maya の UI スレッドがまだ落ち着いていない

**対策**
`cmds.evalDeferred` で **現在のコールバックを完全に抜けてから** 次のステージを実行する。 update フローを 3 段階に分割:

```python
def _update_from_github(*_):
    # Stage 1: ボタン callback は即 return
    cmds.evalDeferred(_run_update, lowestPriority=True)

def _run_update():
    # Stage 2: idle 時に fetch + exec + flush
    source = fetch()
    cmds.deleteUI(WINDOW)          # 自分のウィンドウを閉じる
    exec_install(source)           # ここで modal 出るが問題なし
    flush_sys_modules()
    cmds.evalDeferred(_reopen, lowestPriority=True)  # 更に defer

def _reopen():
    # Stage 3: 次の idle で reopen
    import my_tool
    my_tool.show()
```

**教訓**
Maya の UI コールバックの中で自分自身の親を消してはいけない。破壊系操作は必ず `evalDeferred` で defer する。

---

## 2. 成功パターン ─ 「ホットアップデート可能な Maya ツール」の標準構成

上の全ての落とし穴を回避した、再利用可能な最終構成:

### 2-1. ファイルレイアウト

```
repo-root/
├── install.py                        ← エンドユーザーが唯一手動で扱うファイル
├── <package>/                        ← 実装本体
│   ├── __init__.py                   ← __version__ を必ず持たせる
│   ├── ui.py                         ← Update ボタンを含む UI
│   └── ...
└── <launcher>.py                     ← import <launcher>; launcher.show() で開く
```

### 2-2. install.py がやること

1. `cmds.internalVar(userScriptDir=True)` で Maya ユーザースクリプトフォルダを取得
2. GitHub API で `main` の最新 commit SHA を取得
3. `raw.githubusercontent.com/OWNER/REPO/<SHA>/...` から各ファイルを atomic write でダウンロード
4. `__pycache__` を掃除
5. `sys.modules` から自パッケージを flush
6. `<user_scripts>` を `sys.path` に追加
7. シェルフボタンを追加 (左クリック=起動、右クリック=Update)
8. `confirmDialog` で `previous → current` バージョンを表示

### 2-3. UI が持つべき Update ボタンのロジック

```python
def _update_from_github(*_):
    cmds.evalDeferred(_run_update, lowestPriority=True)

def _run_update():
    # SHA を解決して install.py を SHA-pinned URL で fetch
    sha = _latest_sha()
    url = f"https://raw.githubusercontent.com/OWNER/REPO/{sha}/install.py"
    source = urllib.request.urlopen(url, timeout=30).read()

    # 自ウィンドウを閉じる → install.py 実行 → 再オープン (更に defer)
    if cmds.window(WIN, exists=True):
        cmds.deleteUI(WIN)
    exec(compile(source, "install.py", "exec"),
         {"__name__": "install", "__file__": "<github>"})
    for m in [k for k in list(sys.modules)
              if k == PKG or k.startswith(PKG + ".") or k == LAUNCHER]:
        sys.modules.pop(m, None)
    cmds.evalDeferred(_reopen, lowestPriority=True)

def _reopen():
    import <launcher> as l
    l.show()
```

### 2-4. シェルフボタン

- **左クリック** — 起動コマンド (先に `sys.modules` フラッシュしてから import + show)
- **右クリック** — ポップアップメニューで Launch / Update

Update コマンドは install.py と同じロジック (SHA fetch → exec) を **セルフコンテインな snippet** として書く。パッケージへの依存を持たせない (パッケージが壊れていても Update が走るように)。

### 2-5. UI にバージョン表示

タイトルバーと footer に `__version__` を出しておくと、動作しているコードのバージョンが目視で分かる。開発中もユーザーサポートでも便利。

```python
win = cmds.window(WIN, t=f"My Tool  —  v{__version__}", ...)
cmds.text(l=f"my_tool  v{__version__}", fn="smallObliqueLabelFont", al="right")
```

---

## 3. 検証チェックリスト

新規ツールを作ったら、以下のシナリオを 1 度は通す:

- [ ] 初回インストール — install.py をドラッグ、ダイアログが出る、シェルフボタンが増える
- [ ] 起動 — シェルフボタンをクリック、UI が開き、バージョン表示が正しい
- [ ] GitHub に version bump を push
- [ ] Update — UI 内 Update ボタンをクリック、`previous → current` ダイアログが正しく変わる
- [ ] Update 後 — UI が閉じて再オープンされ、新バージョンが表示される
- [ ] シェルフ右クリック → Update でも同様に動く
- [ ] `.py` の mtime が install 実行時刻に更新されている
- [ ] `__pycache__` が消えて再生成されている
- [ ] Maya を再起動しても最新版が読まれる (`__init__.py` を直接開いて `__version__` を目視)

---

## 4. デバッグ用 診断スニペット

「更新されているはずなのに古い」と言われたときは、まずこれを Script Editor で実行してもらう:

```python
import os, sys, datetime, hashlib
# 一旦 flush してから fresh import
for m in [k for k in list(sys.modules) if k.startswith("<pkg>")]:
    sys.modules.pop(m, None)

import <pkg>
p = <pkg>.__file__
size = os.path.getsize(p)
mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p))
with open(p, "rb") as f:
    sha = hashlib.sha256(f.read()).hexdigest()[:16]

print(f"module   : {p}")
print(f"version  : {<pkg>.__version__}")
print(f"size     : {size} bytes")
print(f"mtime    : {mtime}")
print(f"sha256   : {sha}")
```

得られる情報:

- `mtime` が更新されていない → install が走っていない or copystat 系のバグ
- `mtime` は新しいが `version` が古い → CDN キャッシュ (SHA-pinned URL に切り替え)
- `sha256` が想定と違う → 意図しない別ファイルが混入

---

## 5. 参考実装

> **⚠ この doc を新規ツール開発セッションで読み込ませる場合**
>
> 以下 §5 〜 §7 で「このリポジトリ」「`docs/reference-code/…`」と書かれている
> のは、**この doc が置いてある参照元リポジトリ = `ogshaw03/Stylized-Paint-Projectile-Tool`**
> を指す。あなたが今書いている新ツール リポジトリのことではない。
>
> 新セッションでは、以下の URL 群を **WebFetch で取得してから** コピペ / 書き換え
> ベースの実装を進めること。相対パスとして自分の作業ツリーを検索しない。
>
> - パターン doc (この doc):
>   `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/maya-hot-update-patterns.md`
> - installer テンプレ:
>   `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/reference-code/install.py`
> - ツール本体テンプレ:
>   `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/reference-code/my_tool.py`
> - テンプレ README:
>   `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/reference-code/README.md`

参照元リポジトリ側で上記パターンを全部実装している一次実装:

- `install.py` — SHA-pinned fetch, atomic write, force overwrite, shelf popup
- `paint_projectile/ui.py` — Update ボタン (`_update_from_github` + `_run_update` + `_reopen_after_update`)
- `paint_projectile/__init__.py` — `__version__`

さらに **新規ツール向けにインフラだけ抜き出したテンプレート** が、
参照元リポジトリの `docs/reference-code/` に置いてある (上記 URL 参照):

```
<paint_projectile repo>/docs/reference-code/
├── README.md      ← セットアップ手順 / 検証チェックリスト
├── install.py     ← ドラッグ&ドロップ installer 単体テンプレ
└── my_tool.py     ← ツール本体テンプレ (__version__ + show() + Update)
```

新セッションでは 2 ファイル (`install.py` + `my_tool.py`) を **WebFetch で
取得** → 新ツール リポジトリのルートに置く → 定数書き換え → GitHub push、
で同じ配布・更新体験のツールが立ち上がる。

---

## 6. テンプレの CUSTOMIZE ブロック — 書き換え必須の定数

**参照元リポジトリ側の** テンプレ (§5 の URL 群、参照元 =
`ogshaw03/Stylized-Paint-Projectile-Tool` の `docs/reference-code/install.py` と
`my_tool.py`) は冒頭に `# ─── CUSTOMIZE ───` で挟まれた定数ブロックを持って
いる。**書き換えが必要なのはこのブロックだけ**、他はそのままで動く。

新ツール セッションでは、これら 2 ファイルを WebFetch で取得 → 中身を
新ツール リポジトリのルートに書き出し → 以下の CUSTOMIZE を新ツール向けに
書き換えて GitHub に push、が定型フロー。

### 6-1. `install.py` (5 定数)

```python
# ─── CUSTOMIZE ────────────────────────────────────────────────────────────
_GITHUB_OWNER = "YOUR_GITHUB_USERNAME"
_GITHUB_REPO = "YOUR_REPO_NAME"
_GITHUB_BRANCH = "main"

_MODULE = "my_tool"                     # your tool's .py filename (no .py)
_SHELF_BUTTON_LABEL = "MyTool"          # short label on the shelf button
# ─── END CUSTOMIZE ────────────────────────────────────────────────────────
```

| 定数 | 説明 | 例 |
|---|---|---|
| `_GITHUB_OWNER` | GitHub のアカウント名 / Organization 名 | `"ogshaw03"` |
| `_GITHUB_REPO`  | リポジトリ名 (owner/repo の repo 部分) | `"paint-projectile-tool"` |
| `_GITHUB_BRANCH`| ダウンロード対象ブランチ (通常 `"main"`) | `"main"` |
| `_MODULE`       | ツール本体 `.py` のモジュール名 (`.py` 抜き) | `"paint_projectile"` |
| `_SHELF_BUTTON_LABEL` | シェルフに表示する短い名前 (10 文字以下推奨) | `"PaintFX"` |

### 6-2. `my_tool.py` (4 定数)

```python
WINDOW = "myToolWin"      # match install.py's _close_existing_window() target

# ─── CUSTOMIZE ────────────────────────────────────────────────────────────
_GITHUB_OWNER = "YOUR_GITHUB_USERNAME"
_GITHUB_REPO = "YOUR_REPO_NAME"
_GITHUB_BRANCH = "main"
_PACKAGE = "my_tool"        # matches this file's module name
# ─── END CUSTOMIZE ────────────────────────────────────────────────────────
```

| 定数 | 説明 |
|---|---|
| `_GITHUB_OWNER` / `_GITHUB_REPO` / `_GITHUB_BRANCH` | install.py と **同一値** にする |
| `_PACKAGE` | このファイル自身のモジュール名 (= install.py の `_MODULE`) |
| `WINDOW`   | ツールウィンドウの一意名。install.py の `_close_existing_window` は `f"{_MODULE}Win"` を探すので、**`_MODULE + "Win"` にしておくと自動で一致する** |

### 6-3. モジュール名 = ファイル名 = 3 か所同一

3 か所を一致させることが唯一の落とし穴:

```
実ファイル名:               <MODULE_NAME>.py
install.py の  _MODULE   :  <MODULE_NAME>
my_tool.py の  _PACKAGE  :  <MODULE_NAME>
```

例: 新ツール名を `paint_projectile` にする場合:

```
paint_projectile.py                ← ファイル自体を this にリネーム
install.py:      _MODULE  = "paint_projectile"
paint_projectile.py: _PACKAGE = "paint_projectile"
paint_projectile.py: WINDOW   = "paint_projectileWin"   ← _MODULE + "Win"
```

これ以外 (`_GITHUB_OWNER`, `_GITHUB_REPO`, `_SHELF_BUTTON_LABEL`, `WINDOW`) は
好きに命名して OK。

### 6-4. コード側で書き換えるのは 1 か所だけ

`my_tool.py` の `_build_body()` を自分の UI に置き換える:

```python
def _build_body() -> None:
    """Placeholder tool UI. Replace with your real controls."""
    # ← ここに cmds.textFieldButtonGrp / cmds.floatSliderGrp などを並べる
```

update 関連の関数 (`_resolve_latest_sha`, `update_from_github`, `_run_update`,
`_reopen_after_update`) と `show()` の外枠 (window / footer / Update ボタン) は
**触らない**。

### 6-5. 追加モジュールを作る場合

`my_tool.py` が肥大化してきたら追加ファイルに分割することになる。
その場合の作業:

1. `my_tool/` フォルダ を作って `__init__.py` + サブモジュール群にリファクタ
   (single-file → package 化)
2. `install.py` の `_fetch_module` を「単一ファイルダウンロード」から
   「ファイル一覧ダウンロード」に拡張 → `_REMOTE_FILES` タプルを追加
3. **新規モジュールを追加したら必ず `_REMOTE_FILES` にも追記** (§1-10 で
   踏んだ落とし穴の再発防止)
4. `_flush_imports` をパッケージ全体をポップするパターンに変更

**参照元リポジトリ** (`ogshaw03/Stylized-Paint-Projectile-Tool`) の
`paint_projectile/` パッケージ + そのルート `install.py` が拡張後の実装例
そのもの。以下 URL を WebFetch して参考にする:

- `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/install.py`
- `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/paint_projectile/__init__.py`
- `https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/paint_projectile/ui.py`

---

## 7. 新ツール セッションでの Claude へのプロンプト テンプレ

新ツール開発を Claude に頼む時のプロンプト:

```
新しい Maya ツール "<ツール名>" を作りたい。
配布とアップデートは別リポジトリ (paint_projectile) の参考実装パターンで
組み込んで。以下 3 ファイルを WebFetch で取得して読み込んで:

  https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/maya-hot-update-patterns.md
  https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/reference-code/install.py
  https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/main/docs/reference-code/my_tool.py

参照元リポジトリ (paint_projectile) の中身は真似しない。
上の 2 つの .py の中身を こちら (新ツール リポジトリ) の
ルート に書き出し、CUSTOMIZE ブロック (patterns doc §6) を以下で埋めて:

  GitHub owner: <あなたの GitHub アカウント>
  リポジトリ名: <新リポジトリ名>
  モジュール名: <スネークケース、ファイル名にもする>
  シェルフボタン ラベル: <10 文字以下>

そのあと <ツール名>.py の _build_body() に、以下の機能を実装:

  ・<機能 1>
  ・<機能 2>
  ...

配布インフラは変えず (patterns doc §1-10 に登録忘れ注意)、
ツール中身だけを追加してください。
```

Claude が参考ファイルを読み込んで、CUSTOMIZE ブロックを埋め、
機能実装まで一気にできる。
