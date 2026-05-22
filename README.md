CMYW_Studio
这是一个专为 Bambu Lab 打印机设计的 CMYW 多色光影画（Lithophane）生成工具。通过物理减色原理，该工具能够将普通彩色图片快速转换为适合 3D 打印的 .3mf 模型文件。

功能特点
高效转换：将图像颜色映射为物理层厚度，生成适用于多色打印的模型。

格式兼容：直接输出标准的 .3mf 格式，完美兼容 Bambu Studio。

轻量便捷：纯 Python 实现，依赖少，部署简单。

环境要求
Python 3.8+

依赖库：请查看 requirements.txt

快速开始
1. 安装依赖
在项目目录下运行以下命令安装必要的库：

Bash
pip install -r requirements.txt
2. 运行工具
将你需要转换的图片放入目录，使用以下命令生成模型：

Bash
python main.py --input your_image.jpg --output output_model.3mf
(注：请根据你 main.py 实际支持的参数进行微调)

使用说明
图片选择：建议使用高对比度、光影效果明显的彩色照片。

打印设置：生成的 .3mf 文件导入 Bambu Studio 后，建议使用 0.2mm 层高 并配合相应的 CMYW 耗材 进行切片打印，以达到最佳光影效果。

开源协议
本项目采用 MIT License 开源。
