# ブルドーザの自動施工 ROS2 WorkSpace

## セットアップ
1. 指定箇所に本リポジトリをクローン  
    本ワークスペースは[ROS2-Env](https://github.com/FRL-TAI/ROS2-Env)で指示されているように、ホストOSの`workspaces`ディレクトリにcloneする.
    ``` bash
    cd ~/<開発フォルダ名>/workspaces

    # submoduleの中身まで一緒にclone
    git clone --recursive <本リポジトリのURL>
    ```

2. ROS2-Envコンテナ内で、本ワークスペースを開く  
    コンテナが立ち上がった段階で、パッケージの依存関係の解消とビルドが完了している。  
    詳しくは[ROS2-Env](https://github.com/FRL-TAI/ROS2-Env)の`.devcontainer/devcontainer.json`を参照せよ。


## 基本的な使用方法
1. ROS-TCP-Endpointの起動  
    コンテナ内の本リポジトリ直下のワークスペースで下記を実行し、エンドポイントを起動させる
    ``` bash
    ros2 run ros_tcp_endpoint default_server_endpoint
    ```

2. OperaSim-AGX-TAIの実行ボタンを押す  
    [OperaSim-AGX-TAI](https://github.com/FRL-TAI/OperaSim-AGX-TAI)（[OperaSim-AGX](https://github.com/pwri-opera/OperaSim-AGX)を研究用に拡張したもの）をUnityのProjectとして開き、Unity Editor上部の実行ボタンを押す。  
    詳しい説明は[公式ドキュメント](https://operasim-physx.readthedocs.io/ja/latest/index.html)を参照せよ。


3. ROS Topicを介して通信  
    上記手順を踏み、OperaSim側とROS2側の通信が確認出来たら、ROS Topic等を介して操作を行うことが出来る。

## ディレクトリ構成
```
ws-bulldozer/
├ src/                ROS2 のパッケージ
│  ├ bull_ope/        土質パラメータ推定用のデータ収集（エピソードの実行・記録）
│  ├ ROS-TCP-Endpoint/  Unity との通信（submodule）
│  └ com3_ros/        OperaSim のメッセージ定義など（submodule）
├ analysis/           解析・点検のスクリプト（ビルドせずに python3 で実行する）
│  ├ production/      本番の収集の点検
│  ├ validation/      データ検証の関門1〜7
│  └ phase0/          フェーズ0（締固め・沈下・較正曲線）
├ data/               出力データ（Git の管理外）
└ docs/               ドキュメント（bull_ope/ に索引とサブ文書、関門のレポート）
```

## 各パッケージのドキュメント
- `bull_ope` : [土質パラメータ推定用データ収集パッケージ](/docs/bull_ope/README.md)
- `analysis` : [解析・点検のスクリプトの一覧](/analysis/README.md)
