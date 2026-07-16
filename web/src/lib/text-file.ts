export type DecodedTextEncoding = "utf-8" | "utf-16le" | "utf-16be" | "gb18030";

export type DecodedTextFile = {
  text: string;
  encoding: DecodedTextEncoding;
};

const UTF8_BOM = Uint8Array.from([0xef, 0xbb, 0xbf]);
const UTF16_LE_BOM = Uint8Array.from([0xff, 0xfe]);
const UTF16_BE_BOM = Uint8Array.from([0xfe, 0xff]);

function startsWithBom(bytes: Uint8Array, bom: Uint8Array): boolean {
  if (bytes.length < bom.length) {
    return false;
  }
  return bom.every((value, index) => bytes[index] === value);
}

function tryDecode(
  bytes: Uint8Array,
  encoding: DecodedTextEncoding,
  options?: TextDecoderOptions,
): string | null {
  try {
    return new TextDecoder(encoding, options).decode(bytes);
  } catch {
    return null;
  }
}

function detectUtf16WithoutBom(bytes: Uint8Array): DecodedTextEncoding | null {
  if (bytes.length < 8) {
    return null;
  }

  const sampleSize = Math.min(bytes.length, 512);
  let evenZeroCount = 0;
  let oddZeroCount = 0;
  let evenCount = 0;
  let oddCount = 0;

  // ATP 文本通常以 ASCII 关键字开头，交替空字节是无 BOM UTF-16 的明显特征。
  for (let index = 0; index < sampleSize; index += 1) {
    if (index % 2 === 0) {
      evenCount += 1;
      if (bytes[index] === 0) {
        evenZeroCount += 1;
      }
      continue;
    }

    oddCount += 1;
    if (bytes[index] === 0) {
      oddZeroCount += 1;
    }
  }

  const evenZeroRatio = evenCount === 0 ? 0 : evenZeroCount / evenCount;
  const oddZeroRatio = oddCount === 0 ? 0 : oddZeroCount / oddCount;

  if (oddZeroRatio >= 0.3 && evenZeroRatio <= 0.05) {
    return "utf-16le";
  }
  if (evenZeroRatio >= 0.3 && oddZeroRatio <= 0.05) {
    return "utf-16be";
  }
  return null;
}

export function decodeTextBytes(bytes: Uint8Array): DecodedTextFile {
  if (bytes.length === 0) {
    return { text: "", encoding: "utf-8" };
  }

  if (startsWithBom(bytes, UTF8_BOM)) {
    return {
      text: tryDecode(bytes, "utf-8") ?? "",
      encoding: "utf-8",
    };
  }

  if (startsWithBom(bytes, UTF16_LE_BOM)) {
    return {
      text: tryDecode(bytes, "utf-16le") ?? "",
      encoding: "utf-16le",
    };
  }

  if (startsWithBom(bytes, UTF16_BE_BOM)) {
    return {
      text: tryDecode(bytes, "utf-16be") ?? "",
      encoding: "utf-16be",
    };
  }

  const utf16Encoding = detectUtf16WithoutBom(bytes);
  if (utf16Encoding) {
    const utf16Text = tryDecode(bytes, utf16Encoding);
    if (utf16Text !== null) {
      return { text: utf16Text, encoding: utf16Encoding };
    }
  }

  const utf8Text = tryDecode(bytes, "utf-8", { fatal: true });
  if (utf8Text !== null) {
    return { text: utf8Text, encoding: "utf-8" };
  }

  const gb18030Text = tryDecode(bytes, "gb18030");
  if (gb18030Text !== null) {
    return { text: gb18030Text, encoding: "gb18030" };
  }

  throw new Error("无法识别文件编码，请将 ATP 文本另存为 UTF-8 或 GB18030 后重试。");
}

export async function readTextFile(file: Blob): Promise<DecodedTextFile> {
  const buffer = new Uint8Array(await file.arrayBuffer());
  return decodeTextBytes(buffer);
}
