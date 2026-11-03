// @filter 向量
// @category 輸入
// @description 節點用：照 Blender 的「向量」節點（Vector）：一個常數向量，整張圖的紅綠藍是 X、Y、Z。接到別的節點的向量輸入
// @param vector vec3 0,0,0 -1000000 1000000 "向量"

vec4 effect(vec2 uv) {
    return vec4(vector, 1.0);
}
