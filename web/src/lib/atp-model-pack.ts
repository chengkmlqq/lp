/**
 * ATP 模型文件打包（2026-11-10）：
 * 把「选择文件夹」得到的多文件（webkitRelativePath 带目录前缀）打包成 zip，
 * 剥掉公共目录前缀使 zip 根直接是模型文件（work.atp + lib/dat），
 * 与资产分层目录 /atp-assets/<电压>/<塔型>/<场景>/<避雷器组合> 对齐。
 * 与模型管理页创建表单内的打包逻辑同口径。
 */
export async function packModelFilesZip(files: File[]): Promise<Blob> {
  const JSZip = (await import("jszip")).default;
  const zip = new JSZip();

  const relativePath = (file: File): string => {
    const candidate = file as File & { webkitRelativePath?: string };
    return candidate.webkitRelativePath || file.name;
  };

  const fullPaths = files.map(relativePath);
  let prefixDepth = 0;
  if (fullPaths.length > 0) {
    const firstSegments = fullPaths[0].split("/").filter(Boolean);
    while (
      prefixDepth < firstSegments.length - 1
      && fullPaths.every((path) => path.split("/").filter(Boolean)[prefixDepth] === firstSegments[prefixDepth])
    ) {
      prefixDepth += 1;
    }
  }
  for (const file of files) {
    const pathParts = relativePath(file).split("/").filter(Boolean);
    const strippedPath = pathParts.slice(prefixDepth).join("/");
    if (strippedPath) {
      zip.file(strippedPath, file);
    }
  }
  return zip.generateAsync({ type: "blob" });
}
