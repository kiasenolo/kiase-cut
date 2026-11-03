// @filter 整數向量
// @category 輸入
// @description 節點用：照 Blender 的「整數向量」節點（Integer Vector）：三個整數 (X, Y, Z) 當成向量，整張圖的紅綠藍是這三個整數。接到別的節點的向量輸入
// @param x int 0 -1000000 1000000 "X"
// @param y int 0 -1000000 1000000 "Y"
// @param z int 0 -1000000 1000000 "Z"

vec4 effect(vec2 uv) {
    return vec4(float(x), float(y), float(z), 1.0);
}
