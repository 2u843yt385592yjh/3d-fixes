#!/usr/bin/env python3

import numpy as np
from math import *
import pyasm

# Suppress scientific notation of small floating point values to make matrices
# easier to read:
np.set_printoptions(suppress=True)

def translate(x, y, z, verbose=False):
    if verbose:
        print('''TRANSLATE:  %-8f   %-8f   %-8f''' % (x, y, z))
    return np.matrix([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [x, y, z, 1],
    ])

def scale(x, y, z, verbose=False):
    if verbose:
        print('''    SCALE:  %-8f   %-8f   %-8f''' % (x, y, z))
    return np.matrix([
        [x, 0, 0, 0],
        [0, y, 0, 0],
        [0, 0, z, 0],
        [0, 0, 0, 1],
    ])

def rotate_x(angle, verbose=False):
    if verbose:
        print(''' ROTATE X:  %-8f   %8s   %8s  ''' % (angle, '', ''))
    a = radians(angle)
    return np.matrix([
        [1,       0,      0, 0],
        [0,  cos(a), sin(a), 0],
        [0, -sin(a), cos(a), 0],
        [0,       0,      0, 1],
    ])

def rotate_y(angle, verbose=False):
    if verbose:
        print(''' ROTATE Y:  %8s   %-8f   %8s  ''' % ('', angle, ''))
    a = radians(angle)
    return np.matrix([
        [cos(a), 0, -sin(a), 0],
        [     0, 1,       0, 0],
        [sin(a), 0,  cos(a), 0],
        [     0, 0,       0, 1],
    ])

def rotate_z(angle, verbose=False):
    if verbose:
        print(''' ROTATE Z:  %8s   %8s   %-8f  ''' % ('', '', angle))
    a = radians(angle)
    return np.matrix([
        [ cos(a), sin(a), 0, 0],
        [-sin(a), cos(a), 0, 0],
        [      0,      0, 1, 0],
        [      0,      0, 0, 1],
    ])

def projection(near, far, fov_horiz, fov_vert, verbose=False):
    if verbose:
        print('''PROJECTION: near: %g far: %g H FOV: %g V FOV: %g''' % (near, far, fov_horiz, fov_vert))
    w = 1 / tan(radians(fov_horiz) / 2)
    h = 1 / tan(radians(fov_vert)  / 2)
    q = far / (far - near)

    return np.matrix([
        [w, 0,       0, 0],
        [0, h,       0, 0],
        [0, 0,       q, 1],
        [0, 0, -q*near, 0]
    ])

def projection_nv_equiv(near, far, fov_horiz, fov_vert, separation, convergence):
    '''
    Returns two projection matrices that have an equivelent adjustment to the
    nvidia formula built in, allowing the familiar convergence and separation
    settings to work the same.
    '''
    w = 1 / tan(radians(fov_horiz) / 2)
    h = 1 / tan(radians(fov_vert)  / 2)
    q = far / (far - near)

    left = np.matrix([
        [                      w, 0,       0, 0],
        [                      0, h,       0, 0],
        [            -separation, 0,       q, 1],
        [ separation*convergence, 0, -q*near, 0]
    ])

    right = np.matrix([
        [                      w, 0,       0, 0],
        [                      0, h,       0, 0],
        [             separation, 0,       q, 1],
        [-separation*convergence, 0, -q*near, 0]
    ])

    return (left, right)

def nv_equiv_multiplier(near, far, sep, conv):
    '''
    Returns a matrix that a projection matrix, including a composite MVP or VP
    matrix can be multiplied by in order to add a stereo correction to it.
    '''
    q = far / (far - near)
    return np.matrix([
        [                     1, 0, 0, 0 ],
        [                     0, 1, 0, 0 ],
        [ (sep*conv) / (q*near), 0, 1, 0 ],
        [ sep - (sep*conv)/near, 0, 0, 1 ]
    ])

def nv_equiv_multiplier_inv(near, far, sep, conv):
    '''
    The inverse of the above, for removing a stereo correction from an inverted
    MV or MVP matrix. Simplifies down to a negation of the above.
    '''
    q = far / (far - near)
    return np.matrix([
        [                      1, 0, 0, 0 ],
        [                      0, 1, 0, 0 ],
        [ -(sep*conv) / (q*near), 0, 1, 0 ],
        [ -sep + (sep*conv)/near, 0, 0, 1 ]
    ])

def find_near_far(m):
    '''
    Find the near and far clipping planes from a projection matrix, or a
    composite matrix containing a projection matrix.
    '''
    near_origin = [0, 0, 0, 1] * m.I
    near_origin = near_origin / near_origin[0,3]
    near = (near_origin * m)[0,3]

    far_origin = [0, 0, 1, 1] * m.I
    far_origin = far_origin / far_origin[0,3]
    far = (far_origin * m)[0,3]

    return (near, far)

def fov_w(matrix):
    return degrees(2 * atan(1/matrix[0, 0]))

def fov_h(matrix):
    return degrees(2 * atan(1/matrix[1, 1]))

def adjustment(w, separation, convergence):
    return separation * (w - convergence)

def correct(coord, separation, convergence):
    if isinstance(coord, np.matrix):
        x,y,z,w = coord.tolist()[0]
    else:
        x,y,z,w = coord
    a = adjustment(w, separation, convergence)
    return ([x-a, y, z, w], [x+a, y, z, w])

def multiply(m1, m2):
	'''
	Does a matrix multiplication in a manner than is closer to how it would
	be done in shader assembly.
	'''
	assert(m1.shape == (4,4))
	assert(m2.shape == (4,4))
	t = m2.T
	r = np.matrix([[0.0]*4]*4)
	for y in range(4):
		for x in range(4):
			# r_y = dp4 m1_y t_x
			r[y,x] = np.dot(m1[y].A1, t[x].A1)
	return r

def to_regs(m, start=210):
    for i in range(4):
        print('def c%i, %g, %g, %g, %g' % (start+i, m[i, 0], m[i, 1], m[i, 2], m[i, 3]))

def determinant(m):
    # See also: numpy.linalg.det()
    # http://www.euclideanspace.com/maths/algebra/matrix/functions/inverse/fourD/index.htm
    return \
    m[0,3]*m[1,2]*m[2,1]*m[3,0] - m[0,2]*m[1,3]*m[2,1]*m[3,0] - m[0,3]*m[1,1]*m[2,2]*m[3,0] + m[0,1]*m[1,3]*m[2,2]*m[3,0] + \
    m[0,2]*m[1,1]*m[2,3]*m[3,0] - m[0,1]*m[1,2]*m[2,3]*m[3,0] - m[0,3]*m[1,2]*m[2,0]*m[3,1] + m[0,2]*m[1,3]*m[2,0]*m[3,1] + \
    m[0,3]*m[1,0]*m[2,2]*m[3,1] - m[0,0]*m[1,3]*m[2,2]*m[3,1] - m[0,2]*m[1,0]*m[2,3]*m[3,1] + m[0,0]*m[1,2]*m[2,3]*m[3,1] + \
    m[0,3]*m[1,1]*m[2,0]*m[3,2] - m[0,1]*m[1,3]*m[2,0]*m[3,2] - m[0,3]*m[1,0]*m[2,1]*m[3,2] + m[0,0]*m[1,3]*m[2,1]*m[3,2] + \
    m[0,1]*m[1,0]*m[2,3]*m[3,2] - m[0,0]*m[1,1]*m[2,3]*m[3,2] - m[0,2]*m[1,1]*m[2,0]*m[3,3] + m[0,1]*m[1,2]*m[2,0]*m[3,3] + \
    m[0,2]*m[1,0]*m[2,1]*m[3,3] - m[0,0]*m[1,2]*m[2,1]*m[3,3] - m[0,1]*m[1,0]*m[2,2]*m[3,3] + m[0,0]*m[1,1]*m[2,2]*m[3,3];

def determinant_euclidean(m):
    # Simple case assuming m[0,3] = 0, m[1,3] = 0, m[2,3] = 0, m[3,3] = 1
    # This would be suitable to calculate the inverse of a model-view matrix,
    # for instance
    return 0 \
            + (m[0,0]*m[1,1]*m[2,2]) \
            - (m[0,0]*m[1,2]*m[2,1]) \
            + (m[0,1]*m[1,2]*m[2,0]) \
            - (m[0,1]*m[1,0]*m[2,2]) \
            + (m[0,2]*m[1,0]*m[2,1]) \
            - (m[0,2]*m[1,1]*m[2,0])

def col_major_regs(m):
    r1 = pyasm.Register(m.T.tolist()[0])
    r2 = pyasm.Register(m.T.tolist()[1])
    r3 = pyasm.Register(m.T.tolist()[2])
    r4 = pyasm.Register(m.T.tolist()[3])
    return (r1, r2, r3, r4)

def _determinant_euclidean_asm_col_major(col0, col1, col2):
    tmp0 = pyasm.Register()
    det = pyasm.Register()

    # Do some multiplications & subtractions in parallel with SIMD instructions:
    tmp0.xyz = pyasm.mul(col0.zxy, col1.yzx)            # m0.z*m1.y, m0.x*m1.z, m0.y*m1.x
    tmp0.xyz = pyasm.mad(col0.yzx, col1.zxy, -tmp0.xyz) # m0.y*m1.z - m0.z*m1.y, m0.z*m1.x - m0.x*m1.z, m0.x*m1.y - m0.y*m1.x
    # Now the multiplications:
    tmp0.xyz = pyasm.mul(tmp0.xyz, col2.xyz)
    # Sum it together to get the determinant:
    det.x = pyasm.add(tmp0.x, tmp0.y)
    det.x = pyasm.add(det.x, tmp0.z)

    return det

def determinant_euclidean_asm_col_major(m):
    (col0, col1, col2, _) = col_major_regs(m)
    return _determinant_euclidean_asm_col_major(col0, col1, col2)

def _inverse(m, d):
    n = np.matrix([[0.0]*4]*4)
    n[0,0] = m[1,2]*m[2,3]*m[3,1] - m[1,3]*m[2,2]*m[3,1] + m[1,3]*m[2,1]*m[3,2] - m[1,1]*m[2,3]*m[3,2] - m[1,2]*m[2,1]*m[3,3] + m[1,1]*m[2,2]*m[3,3]
    n[0,1] = m[0,3]*m[2,2]*m[3,1] - m[0,2]*m[2,3]*m[3,1] - m[0,3]*m[2,1]*m[3,2] + m[0,1]*m[2,3]*m[3,2] + m[0,2]*m[2,1]*m[3,3] - m[0,1]*m[2,2]*m[3,3]
    n[0,2] = m[0,2]*m[1,3]*m[3,1] - m[0,3]*m[1,2]*m[3,1] + m[0,3]*m[1,1]*m[3,2] - m[0,1]*m[1,3]*m[3,2] - m[0,2]*m[1,1]*m[3,3] + m[0,1]*m[1,2]*m[3,3]
    n[0,3] = m[0,3]*m[1,2]*m[2,1] - m[0,2]*m[1,3]*m[2,1] - m[0,3]*m[1,1]*m[2,2] + m[0,1]*m[1,3]*m[2,2] + m[0,2]*m[1,1]*m[2,3] - m[0,1]*m[1,2]*m[2,3]
    n[1,0] = m[1,3]*m[2,2]*m[3,0] - m[1,2]*m[2,3]*m[3,0] - m[1,3]*m[2,0]*m[3,2] + m[1,0]*m[2,3]*m[3,2] + m[1,2]*m[2,0]*m[3,3] - m[1,0]*m[2,2]*m[3,3]
    n[1,1] = m[0,2]*m[2,3]*m[3,0] - m[0,3]*m[2,2]*m[3,0] + m[0,3]*m[2,0]*m[3,2] - m[0,0]*m[2,3]*m[3,2] - m[0,2]*m[2,0]*m[3,3] + m[0,0]*m[2,2]*m[3,3]
    n[1,2] = m[0,3]*m[1,2]*m[3,0] - m[0,2]*m[1,3]*m[3,0] - m[0,3]*m[1,0]*m[3,2] + m[0,0]*m[1,3]*m[3,2] + m[0,2]*m[1,0]*m[3,3] - m[0,0]*m[1,2]*m[3,3]
    n[1,3] = m[0,2]*m[1,3]*m[2,0] - m[0,3]*m[1,2]*m[2,0] + m[0,3]*m[1,0]*m[2,2] - m[0,0]*m[1,3]*m[2,2] - m[0,2]*m[1,0]*m[2,3] + m[0,0]*m[1,2]*m[2,3]
    n[2,0] = m[1,1]*m[2,3]*m[3,0] - m[1,3]*m[2,1]*m[3,0] + m[1,3]*m[2,0]*m[3,1] - m[1,0]*m[2,3]*m[3,1] - m[1,1]*m[2,0]*m[3,3] + m[1,0]*m[2,1]*m[3,3]
    n[2,1] = m[0,3]*m[2,1]*m[3,0] - m[0,1]*m[2,3]*m[3,0] - m[0,3]*m[2,0]*m[3,1] + m[0,0]*m[2,3]*m[3,1] + m[0,1]*m[2,0]*m[3,3] - m[0,0]*m[2,1]*m[3,3]
    n[2,2] = m[0,1]*m[1,3]*m[3,0] - m[0,3]*m[1,1]*m[3,0] + m[0,3]*m[1,0]*m[3,1] - m[0,0]*m[1,3]*m[3,1] - m[0,1]*m[1,0]*m[3,3] + m[0,0]*m[1,1]*m[3,3]
    n[2,3] = m[0,3]*m[1,1]*m[2,0] - m[0,1]*m[1,3]*m[2,0] - m[0,3]*m[1,0]*m[2,1] + m[0,0]*m[1,3]*m[2,1] + m[0,1]*m[1,0]*m[2,3] - m[0,0]*m[1,1]*m[2,3]
    n[3,0] = m[1,2]*m[2,1]*m[3,0] - m[1,1]*m[2,2]*m[3,0] - m[1,2]*m[2,0]*m[3,1] + m[1,0]*m[2,2]*m[3,1] + m[1,1]*m[2,0]*m[3,2] - m[1,0]*m[2,1]*m[3,2]
    n[3,1] = m[0,1]*m[2,2]*m[3,0] - m[0,2]*m[2,1]*m[3,0] + m[0,2]*m[2,0]*m[3,1] - m[0,0]*m[2,2]*m[3,1] - m[0,1]*m[2,0]*m[3,2] + m[0,0]*m[2,1]*m[3,2]
    n[3,2] = m[0,2]*m[1,1]*m[3,0] - m[0,1]*m[1,2]*m[3,0] - m[0,2]*m[1,0]*m[3,1] + m[0,0]*m[1,2]*m[3,1] + m[0,1]*m[1,0]*m[3,2] - m[0,0]*m[1,1]*m[3,2]
    n[3,3] = m[0,1]*m[1,2]*m[2,0] - m[0,2]*m[1,1]*m[2,0] + m[0,2]*m[1,0]*m[2,1] - m[0,0]*m[1,2]*m[2,1] - m[0,1]*m[1,0]*m[2,2] + m[0,0]*m[1,1]*m[2,2]
    return n / d

def inverse(m):
    return _inverse(m, determinant(m))

def _inverse_euclidean(m, d):
    # Simplifying on the assumption that the 4th column is 0,0,0,1
    n = np.matrix([[0.0]*4]*4)
    n[0,0] = m[1,1]*m[2,2] - m[1,2]*m[2,1]
    n[1,0] = m[1,2]*m[2,0] - m[1,0]*m[2,2]
    n[2,0] = m[1,0]*m[2,1] - m[1,1]*m[2,0]

    n[0,1] = m[0,2]*m[2,1] - m[0,1]*m[2,2]
    n[1,1] = m[0,0]*m[2,2] - m[0,2]*m[2,0]
    n[2,1] = m[0,1]*m[2,0] - m[0,0]*m[2,1]

    n[0,2] = m[0,1]*m[1,2] - m[0,2]*m[1,1]
    n[1,2] = m[0,2]*m[1,0] - m[0,0]*m[1,2]
    n[2,2] = m[0,0]*m[1,1] - m[0,1]*m[1,0]

    n[0,3] = n[1,3] = n[2,3] = 0

    n[3,0] = - m[3,0]*n[0,0] - m[3,1]*n[1,0] - m[3,2]*n[2,0]
    n[3,1] = - m[3,0]*n[0,1] - m[3,1]*n[1,1] - m[3,2]*n[2,1]
    n[3,2] = - m[3,0]*n[0,2] - m[3,1]*n[1,2] - m[3,2]*n[2,2]
    n[3,3] =   m[0,0]*n[0,0] + m[0,1]*n[1,0] + m[0,2]*n[2,0] # Gut feeling this will always end up as 1
    # assert(n[3,3] == 1)

    return n / d

def inverse_euclidean(m):
    return _inverse_euclidean(m, determinant_euclidean(m))

def _inverse_euclidean_asm_col_major(col0, col1, col2, det):
    '''
    Performs a matrix inverse in a manner as would be done in assembly.
    Note that the input matrix is in column-major order, but the resulting
    inverted matrix will be in ROW-major order.
    '''
    std_consts = pyasm.Register([0, 1, 0.0625, 0.5])
    dst0 = pyasm.Register()
    dst1 = pyasm.Register()
    dst2 = pyasm.Register()
    dst3 = pyasm.Register()
    inv_det = pyasm.Register()

    # 1st row, simplifying by assuimg the 4th column 0,0,0,1
    # dst0.x = (m1.y*m2.z - m1.z*m2.y)
    # dst0.y = (m1.z*m2.x - m1.x*m2.z)
    # dst0.z = (m1.x*m2.y - m1.y*m2.x)
    # dst0.w = 0

    dst0.xyz = pyasm.mul(col1.zxy, col2.yzx)
    dst0.xyz = pyasm.mad(col1.yzx, col2.zxy, -dst0.xyz)

    # 2nd row
    # dst1.x = (col0.z*m2.y - col0.y*m2.z)
    # dst1.y = (col0.x*m2.z - col0.z*m2.x)
    # dst1.z = (col0.y*m2.x - col0.x*m2.y)
    # dst1.w = 0

    dst1.xyz = pyasm.mul(col0.yzx, col2.zxy)
    dst1.xyz = pyasm.mad(col0.zxy, col2.yzx, -dst1.xyz)

    # 3nd row
    # dst2.x = (col0.y*m1.z - col0.z*m1.y)
    # dst2.y = (col0.z*m1.x - col0.x*m1.z)
    # dst2.z = (col0.x*m1.y - col0.y*m1.x)
    # dst2.w = 0

    dst2.xyz = pyasm.mul(col0.zxy, col1.yzx)
    dst2.xyz = pyasm.mad(col0.yzx, col1.zxy, -dst2.xyz)

    # 4th row
    # dst3.x = - col0.w*dst0.x - col1.w*dst1.x - col2.w*dst2.x
    # dst3.y = - col0.w*dst0.y - col1.w*dst1.y - col2.w*dst2.y
    # dst3.z = - col0.w*dst0.z - col1.w*dst1.z - col2.w*dst2.z
    # dst3.w =   col0.x*dst0.x + col1.x*dst1.x + col2.x*dst2.x (always 1?)

    dst3.xyzw = pyasm.mul(col0.wwwx, dst0.xyzx)
    dst3.xyzw = pyasm.mad(col1.wwwx, dst1.xyzx, dst3.xyzw)
    dst3.xyzw = pyasm.mad(col2.wwwx, dst2.xyzx, dst3.xyzw)
    dst3.xyz  = pyasm.mov(-dst3)

    # Multiply against 1/determinant (and zero out 4th column):
    inv_det.x = pyasm.rcp(det.x)
    inv_det.y = pyasm.mov(std_consts.x)
    dst0 = pyasm.mul(dst0, inv_det.xxxy)
    dst1 = pyasm.mul(dst1, inv_det.xxxy)
    dst2 = pyasm.mul(dst2, inv_det.xxxy)
    dst3 = pyasm.mul(dst3, inv_det.xxxx)

    # Note that this matrix has been transposed and is now in ROW major order!

    return (dst0, dst1, dst2, dst3)

def inverse_euclidean_asm_col_major(m):
    (col0, col1, col2, _) = col_major_regs(m)
    det = _determinant_euclidean_asm_col_major(col0, col1, col2)
    return _inverse_euclidean_asm_col_major(col0, col1, col2, det)

def inverse_matrix_euclidean_m0(m, d):
    # Return the 1st row of an inverted matrix, simplifying on the assumption
    # that the 4th column is 0,0,0,1
    m00 = m[1,1]*m[2,2] - m[1,2]*m[2,1]
    m01 = m[0,2]*m[2,1] - m[0,1]*m[2,2]
    m02 = m[0,1]*m[1,2] - m[0,2]*m[1,1]
    return (m00 / d, m01 / d, m02 / d, 0)

def mv_mvp_m00i(mv, mvp):
    # Take a model-view matrix and a model-view projection matrix and calculate
    # the top left square of the inverse projection matrix making assumptions
    # about the structure of the projection matrix to simplify the calculation.
    #
    # 1. Calculate the determinant of the model-view matrix, simplifying on the
    #    assumption that the 4th column is 0,0,0,1:
    d = determinant_euclidean(mv)

    # 2. Calculate the 1st row of the inverted model-view matrix:
    mvi = inverse_matrix_euclidean_m0(mv, d)

    # 3. Multiply the 1st row of the inverted model-view matrix with the 1st
    #    column of the model-view-projection matrix:
    p00 = (mvi[0] * mvp[0,0] + \
           mvi[1] * mvp[1,0] + \
           mvi[2] * mvp[2,0])

    # 4. Calculate the top-left cell of the inverse projection matrix, which
    #    thanks to the structure of a projection matrix (even an off-center
    #    one) turns out to simplify down to:
    return 1 / p00

# So, the assembly should be something like this, which will save us using up
# one of the two matrix copy slots in Helix mod where we only need to invert a
# local MV matrix to multiply against a local MVP matrix, which I do in Unity
# games some of the time (NOTE: Unverified!):
#
# // 1. Calculate 1/determinant of the MV matrix, simplifying by assuming the
# //    4th column of the MV matrix is 0,0,0,1
# //
# // mathomatic simplified it to:
# // 1 / ((m12*((m20*m01) - (m21*m00))) + (m02*((m21*m10) - (m20*m11))) + (m22*((m00*m11) - (m01*m10))));
# //
# // Replace row numbers with register components (assumes column-major order):
# //   (mv2.x*((mv0.y*mv1.z) - (mv0.z*mv1.y)))
# // + (mv2.y*((mv0.z*mv1.x) - (mv0.x*mv1.z)))
# // + (mv2.z*((mv0.x*mv1.y) - (mv0.y*mv1.x)))
#
# // Do some multiplications in parallel with SIMD instructions:
# mov r22.xyz, mv1
# mul r20.xyz, mv0.yzx, r22.zxy	// mv0.y*mv1.z, mv0.z*mv1.x, mv0.x*mv1.y
# mul r21.xyz, mv0.zxy, r22.yzx	// mv0.z*mv1.y, mv0.x*mv1.z, mv0.y*mv1.x
# // Do the subtractions:
# add r20.xyz, r20.xyz, -r21.xyz // mv0.y*mv1.z - mv0.z*mv1.y, mv0.z*mv1.x - mv0.x*mv1.z, mv0.x*mv1.y - mv0.y*mv1.x
# // Now the multiplications:
# mul r20.xyz, r20.xyz, mv2.xyz
# // Sum it together to get the determinant:
# add r22.w, r20.x, r20.y
# add r22.w, r22.w, r20.z
# // And finally get 1/determinant:
# rcp r22.w, r22.w
#
# // 2. Calculate the 1st row of the inverted MV matrix, simplifying by assuimg
# //    the 4th column of the MV matrix is 0,0,0,1
# //
# // m00 = (mv1.y*mv2.z - mv1.z*mv2.y) / determinant
# // m01 = (mv1.z*mv2.x - mv1.x*mv2.z) / determinant
# // m02 = (mv1.x*mv2.y - mv1.y*mv2.x) / determinant
#
# // Do some multiplications in parallel with SIMD instructions:
# mul r20.xyz, r22.yzx, mv2.zxy // mv1.y*mv2.z, mv1.z*mv2.x, mv1.x*mv2.y
# mul r21.xyz, r22.zxy, mv2.yzx // mv1.z*mv2.y, mv1.x*mv2.z, mv1.y*mv2.x
# // Do the subtractions:
# add r20.xyz, r20.xyz, -r21.xyz // mv1.y*mv2.z - mv1.z*mv2.y, mv1.z*mv2.x - mv1.x*mv2.z, mv1.x*mv2.y - mv1.y*mv2.x
# // Multiply against 1/determinant:
# mul r20.xyz, r20.xyz, r22.www
#
# // 3. Multiply the first row of the inverted MV matrix with the 1st column of
# //    the MVP matrix (MV.I[0,3] is 0, so only worry about the 1st three):
# dp3 r20.x, r20.xyz, mvp0.xyz
#
# // 4. Calculate the top-left cell of the inverse projection matrix,
# //    simplifying based on assumptions about the structure of a projection
# //    matrix (should even work for off-center projection matrices):
# rcp r20.x, r20.x

def random_euclidean_matrix(multiplier=1):
    '''
    Generates a matrix with random euclidean transformations applied to it in a
    random order. Useful for testing simplified matrix algorithms that are
    supposed to work on matrices that do not use the homogeneous 4th
    coordinate but have no other assumptions (e.g. model-view, but not
    model-view-projection).
    '''
    import random
    m = np.identity(4)
    steps = random.randint(1,10)
    for i in range(steps):
        choice = random.randrange(5)
        if choice == 0:
            m = m * translate(random.random() * multiplier, random.random() * multiplier, random.random() * multiplier, verbose=True)
        if choice == 1:
            m = m * scale(random.random() * multiplier, random.random() * multiplier, random.random() * multiplier, verbose=True)
        if choice == 2:
            m = m * rotate_x(random.random() * 180, verbose=True)
        if choice == 3:
            m = m * rotate_y(random.random() * 180, verbose=True)
        if choice == 4:
            m = m * rotate_z(random.random() * 180, verbose=True)
    return m

def random_projection_matrix():
    import random
    near = random.random() * 10 + 1e-45 # Near cannot be 0, so add the minimum non-zero value a 32bit float can hold
    far = near + random.random() * 1000
    fov_h = random.uniform(60,110)
    fov_v = random.uniform(60,90)
    return projection(near, far, fov_h, fov_v, verbose=True)

def random_mvp():
    mv = random_euclidean_matrix()
    p = random_projection_matrix()
    return mv * p
