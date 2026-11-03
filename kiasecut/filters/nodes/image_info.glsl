// @filter 圖像資訊
// @category 輸入
// @description 節點用：照 Blender 的「圖像資訊」節點（Image Info）：圖像的大小（寬、高，單位是像素），每個輸出是一張向量圖（紅綠藍是 X、Y、Z）。尺寸和解析度是 (寬, 高, 0)，位置是 (0, 0, 0)，旋轉是 0，縮放是 (1, 1, 0)（沒有被變換過的圖像都是這樣）
// @output dimensions "尺寸"
// @output resolution "解析度"
// @output location "位置"
// @output rotation "旋轉"
// @output scale "縮放"

vec4 effect(vec2 uv) {
    switch (output_index) {
    case 0:
    case 1: return vec4(resolution, 0.0, 1.0);
    case 2: return vec4(0.0, 0.0, 0.0, 1.0);
    case 3: return vec4(0.0, 0.0, 0.0, 1.0);
    }
    return vec4(1.0, 1.0, 0.0, 1.0);
}
