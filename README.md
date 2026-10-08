# ブルドーザの自動施工 ROS2 WorkSpace

## セットアップ
1. 指定箇所に本リポジトリをクローン  
    本ワークスペースは[FRL-ROS2-Env](https://github.com/gomadare111/FRL-ROS2-Env)で指示されているように、ホストOSの`workspaces`ディレクトリにcloneする.
    ``` bash
    cd ~/<開発フォルダ名>/workspaces

    # submoduleの中身まで一緒にclone
    git clone --recursive <本リポジトリのURL>
    ```

2. FRL-ROS2-Envコンテナ内で、本ワークスペースを開く  
    コンテナが立ち上がった段階で、パッケージの依存関係の解消とビルドが完了している。  
    詳しくは[FRL-ROS2-Env](https://github.com/gomadare111/FRL-ROS2-Env)の`./devcontainer/devcontainer.json`を参照せよ。


## 基本的な使用方法
1. ROS-TCP-Endpointの起動  
    コンテナ内の本リポジトリ直下のワークスペースで下記を実行し、エンドポイントを起動させる
    ``` bash
    ros2 run ros_tcp_endpoint default_server_endpoint
    ```

2. OperaSim-AGXの実行ボタンを押す  
    [OperaSim-AGX](https://github.com/pwri-opera/OperaSim-AGX)をUnityのProjectとして開き、Unity Editor上部の実行ボタンを押す。  
    詳しい説明は[公式ドキュメント](https://operasim-physx.readthedocs.io/ja/latest/index.html)を参照せよ。


3. ROS Topicを介して通信  
    上記手順を踏み、OperaSim側とROS2側の通信が確認出来たら、ROS Topic等を介して操作を行うことが出来る。

## 各パッケージのドキュメント
- `bull_ope` : [作業データ収集用パッケージ](/docs/bull_ope.md)