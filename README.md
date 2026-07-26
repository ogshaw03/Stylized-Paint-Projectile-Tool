# Stylized Paint Projectile Tool — Prototype

Maya 2023 / Python 向けの、アニメ作品用「ペイント弾／液体弾」プロトタイプツールです。
このリポジトリは仕様書 Section 24 のプロトタイプスコープ (項目 1〜10) を実装しています。

- 自動生成された放物線軌道は **下書き** として扱い、破壊しません。
- アニメーターは **World Offset / Camera Offset / Trajectory Time** をキーで自由に調整できます。
- 弾は普通の Polygon Mesh。任意の Shader (Arnold / Toon / Ramp 等) をそのまま使えます。

---

## Prototype スコープ

| # | 実装項目 | 実装場所 |
|---|---|---|
| 1 | Projectile Mesh 指定 | `system.create_projectile_system(mesh=...)` |
| 2 | Start / Target 指定 | 同上 (`start`, `target` 引数) |
| 3 | 放物線 Trajectory 自動生成 | `trajectory.solve_ballistic` + `generate_positions` |
| 4 | 弾 Geometry を軌道上で移動 | `plusMinusAverage` → `projectile.translate` |
| 5 | Animator Offset Controller | `<name>_CTRL` (nurbsCircle) |
| 6 | Offset 非破壊調整 (Key 可) | `worldOffsetX/Y/Z` (Keyable) |
| 7 | Trajectory Time Attribute | `trajectoryTime` (Keyable, 識別キー付き) |
| 8 | タメ・ツメ演出 | `trajectoryTime` を Graph Editor で編集 |
| 9 | Camera Space Offset | `cameraOffsetX/Y`, `cameraDepth` + `pointMatrixMult` |
| 10 | Auto Smear 用 Velocity | `velocityX/Y/Z`, `velocityMagnitude` (readonly output) |

Smear / Collision / Splat / Droplet は今後の段階で追加予定。

---

## インストール

### 方法 A ─ ワンクリック インストーラ (推奨)

`install.py` を Maya のビューポートに **ドラッグ&ドロップ** するだけで、

1. `paint_projectile/` パッケージと `paint_projectile_launch.py` を
   Maya のユーザースクリプトフォルダにコピー
   (例: `Documents/maya/2023/scripts/`)
2. `sys.path` に自動追加
3. 現在アクティブなシェルフに **PaintFX ボタン** を追加

が完了します。以降はシェルフボタンを押すだけで UI が起動します。

Script Editor から実行する場合は Python タブで:

```python
exec(open(r"C:/path/to/Stylized-Paint-Projectile-Tool/install.py").read())
```

再実行しても安全 (既存インストールを上書きします)。

### 方法 B ─ PYTHONPATH を直接指定

`Maya.env` に追記:

```
PYTHONPATH = C:/path/to/Stylized-Paint-Projectile-Tool
```

Maya 再起動後に読み込まれます。開発中でリポジトリのファイルをそのまま編集したい場合はこちら。

## 使い方

### 1) UI から

インストーラを使った場合はシェルフの **PaintFX** ボタンをクリック。
手動で開くなら Script Editor の Python タブで:

```python
import paint_projectile_launch
paint_projectile_launch.show()
```

UI 上で、

1. `Mesh` : 弾として使う Polygon Mesh を選んで **Set Selected**
2. `Start` / `Target` : Locator を選んで **Set Selected**
3. `Camera` (省略可) : Camera Space Offset に使うカメラ
4. Speed / Gravity / Frame Range / Name を調整
5. **GENERATE** をクリック

生成後、`<name>_CTRL` が Selection に入っています。
Graph Editor で以下の Attribute を Key してください。

- `worldOffsetX/Y/Z` — フレーム単位の位置調整
- `cameraOffsetX/Y`, `cameraDepth` — 画面内での逃がし
- `trajectoryTime` — 軌道上のタイミング (タメ・ツメ)

### 2) スクリプトから

```python
from paint_projectile import create_projectile_system

system = create_projectile_system(
    mesh="pSphere1",
    start="startLoc",
    target="targetLoc",
    speed=25.0,
    gravity=9.8,
    start_frame=1,
    end_frame=48,
    name="paintBall_01",
    camera="persp",   # 省略時はアクティブカメラ
)

print(system.controller)   # -> "paintBall_01_CTRL"
```

---

## 生成される構造

```
<name>_GRP
├── <name>_CTRL         (nurbsCircle : 全 Keyable Attribute を保持)
└── <name>_projectile   (transform : 合成結果を translate に受ける)
    └── <name>_mesh     (元 Mesh の複製)
```

依存ノード (`_GRP` 下ではなく DG 上に存在):

- `<name>_baseX / _baseY / _baseZ` — 軌道サンプル (animCurveUL, input=trajectoryTime)
- `<name>_velX  / _velY  / _velZ`  — Velocity サンプル (animCurveUL)
- `<name>_camMult`                 — cameraOffset を World Space に変換 (pointMatrixMult)
- `<name>_negDepth`                — cameraDepth の符号反転 (multiplyDivide)
- `<name>_sum`                     — base + world + camera 合成 (plusMinusAverage)
- `<name>_velMag`                  — Velocity magnitude (distanceBetween)

Base 軌道は `<name>_baseX/Y/Z` に一度だけ書き込まれ、以降は変更しません。
アニメーターの調整は **すべて** Controller 側の Keyable Attribute に乗るため、
Base Trajectory を破壊せずに演出を積めます。

## 評価式

```
Projectile.translate =
    (baseX(trajectoryTime), baseY(trajectoryTime), baseZ(trajectoryTime))
  + (worldOffsetX,          worldOffsetY,          worldOffsetZ)
  + Camera.worldMatrix ⋅ (cameraOffsetX, cameraOffsetY, -cameraDepth)
```

`trajectoryTime` はデフォルトで `startFrame` から `endFrame` へ線形補間する
2 キーが打たれています。動画的な「タメ・ツメ」はこのカーブに中間キーを
追加することで表現します。

---

## テスト

Trajectory 系の計算は Maya 非依存のため、通常の Python から走らせられます。

```
python -m unittest tests.test_trajectory
```

---

## 今後の拡張予定 (仕様書 §11-§20)

- Stylized Smear (BlendShape / Lattice / Curve Deformer)
- Collision Detection & Impact Frame 検出
- Splat Geometry のランダム生成
- Secondary Droplets
- Viewport Trajectory Edit Mode (Locator による直接編集)
- Bake to Geometry
