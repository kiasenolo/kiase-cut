// @filter 黑體
// @category 轉換器
// @description 節點用：照 Blender 的「黑體」節點（Blackbody）：溫度（單位 K）換成黑體輻射的顏色，一張純色的圖（暖色在低溫、藍白在高溫，6500 K 接近白；800 K 以下和 12000 K 以上不再變）。溫度是數字（圖進來就是黑白的明度），沒接線就用欄位裡的數字
// @source "溫度" temperature
// @param temperature float 6500 0 20000 "溫度 (K)"
// @socket in - float
// @socket out - color

// Reimplementation of Blender's Blackbody compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Blender's own fit of the blackbody colour (colorspace code of Blender 5.2): per range of temperature R and G are a / T + b T + c,
// B a cubic, found back from Blender's results (within 5e-6 at every 25 K from 700 to 12500).
const int SEGMENTS = 7;
const float EDGE[8] = float[8](800.0, 965.0, 1167.0, 1449.0, 1902.0, 3315.0, 6365.0, 12000.0);
const float RC[21] = float[21](1619.18676, -0.00205011486, 5.02996767, 2488.4889, -0.00111327924, 3.22615137, 3341.40473, -0.000486567422, 1.76490972, 4094.62204, -0.000127445235, 0.725726581, 4670.27794, 2.91253866e-05, 0.126705526, 4595.09057, 2.87495053e-05, 0.150345572, 3787.17519, 9.35908512e-06, 0.399075727);
const float GC[21] = float[21](0, 0, 0, -755.9907, 0.000316733289, 0.478299375, -1023.6417, 0.000120222159, 0.936665502, -1265.71706, 4.87202079e-06, 1.27054969, -1425.29365, -4.01150781e-05, 1.439728, -1175.54864, -2.16378223e-05, 1.30408042, -500.799531, -4.59832099e-06, 1.09098769);
const float BC[28] = float[28](0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -1.97074546e-11, 1.75358346e-07, -0.000250540091, -0.022280777, -1.61997741e-13, -1.64215998e-08, 0.000386216253, -0.738077348, 6.7264697e-13, -2.73077865e-08, 0.000424097389, -0.752333083);

vec3 blackbody(float t) {
    if (t >= 12000.0) return vec3(0.826295495, 0.994508028, 1.56630766);
    if (t < 800.0) return vec3(5.41329, 0.0, 0.0);
    int i = 0;
    for (int k = 1; k < SEGMENTS; k++) if (t >= EDGE[k]) i = k;
    float r = RC[3 * i] / t + RC[3 * i + 1] * t + RC[3 * i + 2];
    float g = GC[3 * i] / t + GC[3 * i + 1] * t + GC[3 * i + 2];
    float b = ((BC[4 * i] * t + BC[4 * i + 1]) * t + BC[4 * i + 2]) * t + BC[4 * i + 3];
    return max(vec3(r, g, b), 0.0) * vec3(1.0, i == 0 ? 0.0 : 1.0, 1.0);
}

float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }

vec4 effect(vec2 uv) {
    return vec4(blackbody(has_src() ? bright(src(uv)) : temperature), 1.0);
}
