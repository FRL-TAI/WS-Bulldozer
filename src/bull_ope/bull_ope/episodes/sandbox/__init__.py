"""本番の収集には使わないエピソード。名前は ex_ で始まる。

- ROS 側（エピソード）で変えられる自由度（動き・土質・地形）を一通り示すサンプル
- 試作中のエピソード（本番に使うと決めたら dataset/ に移し、名前を dataset_* に変える）
- 旧版のエピソード（ex_flat_constant、ex_compacted_strips、ex_shuttle_3x5m）

すべて `test_episode` から実行できる。
地形の加工（terrain_ops）を使うものは、Unity 側で AGX_GRID_CONTROL を有効にしないとスキップされる。
"""
