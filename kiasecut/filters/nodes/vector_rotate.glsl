// @filter 向量旋轉
// @category 向量
// @description 節點用：照 Blender 的「向量旋轉」：圖像的紅綠藍當成向量 (X, Y, Z)，繞著中心旋轉（中心、軸、旋轉沒接圖就用欄位裡的向量）。類型：軸與角度（繞任意軸）、X／Y／Z 軸、歐拉 XYZ（先繞 X、再 Y、再 Z）；反轉就轉回去。欄位的角度用度；從別的節點接進來的角度數字當弧度（像 Blender）
// @source "向量"
// @input center "中心"
// @input axis "軸"
// @input angle "角度" angle
// @input rotation "旋轉"
// @param kind menu 軸與角度 "軸與角度|X 軸|Y 軸|Z 軸|歐拉 XYZ" "類型"
// @param invert bool false "反轉"
// @param vec_center vec3 0,0,0 -1000000 1000000 "中心"
// @param vec_axis vec3 0,0,1 -1000000 1000000 "軸"
// @param angle float 0 -36000 36000 "角度（度）"
// @param vec_rotation vec3 0,0,0 -36000 36000 "旋轉（度）"
// @show axis kind == 軸與角度
// @show vec_axis kind == 軸與角度
// @show angle kind != 歐拉 XYZ
// @show rotation kind == 歐拉 XYZ
// @show vec_rotation kind == 歐拉 XYZ

// Reimplementation of Blender's Vector Rotate compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Checked against Blender 5.2 (Rodrigues' rotation about the axis; Euler XYZ = Rz Ry Rx, the inverse is the transpose).

vec3 rodrigues(vec3 v, vec3 axis, float ang) {
    float l = length(axis);
    if (l == 0.0) return v;
    vec3 k = axis / l;
    return v * cos(ang) + cross(k, v) * sin(ang) + k * dot(k, v) * (1.0 - cos(ang));
}

vec3 vec_in(bool linked, vec4 c, vec3 field) { return linked ? unpremultiply(c).rgb : field; }

vec4 effect(vec2 uv) {
    vec4 s = unpremultiply(src(uv));
    vec3 centre = vec_in(has_input_center(), input_center(uv), vec_center);
    vec3 v = s.rgb - centre;
    float ang = has_input_angle() ? dot(input_angle(uv).rgb, vec3(0.2126, 0.7152, 0.0722)) : radians(angle);
    if (invert) ang = -ang;
    vec3 r;
    if (kind == 0) r = rodrigues(v, vec_in(has_input_axis(), input_axis(uv), vec_axis), ang);
    else if (kind == 1) r = rodrigues(v, vec3(1.0, 0.0, 0.0), ang);
    else if (kind == 2) r = rodrigues(v, vec3(0.0, 1.0, 0.0), ang);
    else if (kind == 3) r = rodrigues(v, vec3(0.0, 0.0, 1.0), ang);
    else {
        vec3 e = has_input_rotation() ? unpremultiply(input_rotation(uv)).rgb : radians(vec_rotation);
        float cx = cos(e.x), sx = sin(e.x), cy = cos(e.y), sy = sin(e.y), cz = cos(e.z), sz = sin(e.z);
        mat3 rx = mat3(1.0, 0.0, 0.0, 0.0, cx, sx, 0.0, -sx, cx);       // (GLSL mat3 takes columns)
        mat3 ry = mat3(cy, 0.0, -sy, 0.0, 1.0, 0.0, sy, 0.0, cy);
        mat3 rz = mat3(cz, sz, 0.0, -sz, cz, 0.0, 0.0, 0.0, 1.0);
        mat3 m = rz * ry * rx;
        r = invert ? transpose(m) * v : m * v;
    }
    return premultiply(vec4(r + centre, s.a));
}
