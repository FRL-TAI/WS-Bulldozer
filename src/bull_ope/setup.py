from setuptools import find_packages, setup

package_name = 'bull_ope'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='riku.tai.16@gmail.com',
    description='OperaSim-AGX のブルドーザで押土のエピソードを実行し、土質パラメータ推定用のデータを記録する',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'collect_data = bull_ope.apps.collect_data:main',
            'test_episode = bull_ope.apps.test_episode:main',
        ],
    },
)
