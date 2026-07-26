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

このリポジトリ自体が上記パターンを全部実装している:

- `install.py` — SHA-pinned fetch, atomic write, force overwrite, shelf popup
- `paint_projectile/ui.py` — Update ボタン (`_update_from_github` + `_run_update` + `_reopen_after_update`)
- `paint_projectile/__init__.py` — `__version__`

新しい Maya ツールを作るときは、これらのファイルをテンプレとしてコピー → 定数
(`_GITHUB_OWNER`, `_GITHUB_REPO`, `_PACKAGE`, `_LAUNCHER`, `_SHELF_BUTTON_LABEL` など)
を置換すれば同じ体験のツールが 30 分で立ち上がる。
