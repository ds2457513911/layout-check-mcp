import os
import requests
from tqdm import tqdm

# 修改为你想要的本地保存路径
local_dir = r"C:\Users\ds245\.cache\huggingface\hub\models--vikhyatk--moondream2"
os.makedirs(local_dir, exist_ok=True)

# 仓库里所有的 32 个文件（按你截图完整整理）,文件太大的手动下载
# "model.safetensors",               # PyTorch 权重 (3.85 GB)
# "moondream2-mmproj-f16.gguf",      # GGUF 视觉投影文件 (910 MB)
# "moondream2-text-model-f16.gguf",  # GGUF 文本模型文件 (2.84 GB)
files = [
    ".gitattributes",
    "README.md",
    "added_tokens.json",
    "config.json",
    "config.py",
    "configuration_moondream.py",
    "fourier_features.py",
    "generation_config.json",
    "handler.py",
    "hf_moondream.py",
    "image_crops.py",
    "layers.py",
    "merges.txt",
    "modeling_phi.py",
    "moondream.py",
    "region.py",
    "region_model.py",
    "requirements.txt",
    "rope.py",
    "special_tokens_map.json",
    "text.py",
    "tokenizer.json",
    "tokenizer_config.json",
    "utils.py",
    "versions.txt",
    "vision.py",
    "vision_encoder.py",
    "vocab.json",
    "weights.py"
]

base_url = "https://hf-mirror.com/vikhyatk/moondream2/resolve/2025-01-09/"

print(f"准备下载 {len(files)} 个文件到 {local_dir} ...")
print("如果下载过慢或断流，可以按 Ctrl+C 中断，重新运行脚本会跳过已下载的文件。\n")

for filename in files:
    url = base_url + filename
    dest = os.path.join(local_dir, filename)
    
    # 断点续传：如果文件已经存在且大小不为0，跳过
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"⏭️ 已存在，跳过: {filename}")
        continue
        
    print(f"⬇️ 正在下载: {filename}")
    try:
        # 使用 stream 模式下载大文件
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        with open(dest, 'wb') as f, tqdm(
            desc=filename,
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(chunk_size=1024*1024): # 每次1MB
                size = f.write(data)
                bar.update(size)
    except Exception as e:
        print(f"❌ 下载 {filename} 失败: {e}")
        print("   可以稍后重新运行脚本，或者手动在浏览器中点击下载该文件。")

print("\n🎉 下载流程结束！")