type CoordinateSystemUnion =
  | "UNSPECIFIED"
  | "RDF"
  | "RUF"
  | "RDB"
  | "RUB"
  | "LDF"
  | "LUF"
  | "LDB"
  | "LUB";

export type GaussianCloud = {
  numPoints: number;
  shDegree: number;
  antialiased: boolean;
  positions: Float32Array;
  scales: Float32Array;
  rotations: Float32Array;
  alphas: Float32Array;
  colors: Float32Array;
  sh: Float32Array;
};

export type ILoadSpzOptions = {
  colorScaleFactor?: number;
  unpackOptions?: {
    coordinateSystem?: CoordinateSystemUnion;
  };
};

function createUnsupportedSpzError(): Error {
  return new Error("SPZ Gaussian splat decoding is disabled in this build.");
}

export async function loadSpz(
  _spzData: Uint8Array | ArrayBuffer,
  _options?: ILoadSpzOptions,
): Promise<GaussianCloud> {
  throw createUnsupportedSpzError();
}

export async function loadSpzFromUrl(
  _url: string,
  _options?: ILoadSpzOptions,
): Promise<GaussianCloud> {
  throw createUnsupportedSpzError();
}
