from numpy import array, ones, zeros, eye, size, sqrt, pi, diag
from numpy.linalg import inv, eig, matrix_power
from scipy.linalg import expm
from .robotics_helpfuns import skew

from vpython import canvas, vector, color, rate, cylinder
from .vpython_ext import vellipsoid

class RigidBody():
    
    def __init__( self, m_B=1, B_I_B=eye(3), I_grav=array([[0,0,-9.81]]).T ):
        # link body to joints
        self.childJoints = array([])
        self.parentJoint = array([])
        
        # body properties
        self.m_B    = array(m_B)
        self.B_I_B  = array(B_I_B)

        # gravity vector
        self.I_grav = array(I_grav)
        
        # body state
        self.A_IB          = eye(3)          # The rotational orientation of the body B with respect to the inertial frame
        self.B_omega_B     = zeros([3,1])    # The absolute angular velocity [rad/s]
        self.B_omegaDot_B  = zeros([3,1])    # The absolute angular acceleration  [rad/s^2]
        self.B_r_IB        = zeros([3,1])    # The displacement of the body's COG [m]
        self.B_v_B         = zeros([3,1])    # The absolute velocity of the body's COG [m/s]
        self.B_a_B         = zeros([3,1])    # The absolute acceleration of the body's COG [m/s^2]

    @property
    def nChildren(self):
        return size(self.childJoints)
    
    @property
    def isLeaf(self):
        return self.nChildren == 0
    
    @property
    def isRoot(self):
        return size(self.parentJoint) == 0

    def integrationStep( self, delta_t=0.001 ):
        # Using the M = skew(w) function which is defined below, we compute the 
        # skew symmetric matrices of omega_B in I and in B-coordinates: 
        B_omega_IB = skew(self.B_omega_B)
        I_omega_IB = skew(self.A_IB @ self.B_omega_B)
        
        # Doing one-step Euler forward integration for linear motion
        # while taking into account that we do so in a moving coordinate system:  
        self.B_r_IB = self.B_r_IB + delta_t * (self.B_v_B - B_omega_IB @ self.B_r_IB)
        self.B_v_B  = self.B_v_B  + delta_t * (self.B_a_B - B_omega_IB @ self.B_v_B)
        # Using the matrix-exponential to compute A_IB exactly over the course of one integration time-step.
        self.A_IB   = expm(delta_t*I_omega_IB) @ self.A_IB
        # Doing one-step Euler forward integration for angular velocity:
        self.B_omega_B  = self.B_omega_B + delta_t * (self.B_omegaDot_B - 0)


    def I_r_IQ( self, B_r_BQ ):
        ''' return position of point '''
        return self.A_IB @ (self.B_r_IB + B_r_BQ)
    
    def I_v_Q( self, B_r_BQ ):
        ''' return velocity of point '''
        B_omega_IB = skew(self.B_omega_B)
        return self.A_IB @ (self.B_v_B + B_omega_IB @ B_r_BQ)
    
    def I_a_Q( self, B_r_BQ ): # -> I_a_Q
        ''' return acceleration of point '''
        B_omega_IB = skew(self.B_omega_B)
        B_omegaDot_IB = skew(self.B_omegaDot_B)
        return self.A_IB @ (self.B_a_B + (B_omegaDot_IB + matrix_power(B_omega_IB,2) ) @ B_r_BQ)

    def computeNaturalDynamics( self ):
        # Since no external forces or moments are acting, the change of
        # angular momentum and linear moment is zero:
        B_pDot   = zeros([3,1])
        B_LDot_B = zeros([3,1])
        # Compute the current angular momentum and the skew symmetric
        # matrix of B_omega_B
        B_L_B = self.B_I_B @ self.B_omega_B
        B_omega_IB = skew(self.B_omega_B)
        # Compute accelerations from the equations of motion of a rigid
        # body.  Note that instead of using inv(B_I_B), we're using the
        # matrix 'devision' '\' that Matlab implements ("...X = A\B is
        # the solution to the equation A*X = B..."):   
        self.B_a_B         = B_pDot / self.m_B
        self.B_omegaDot_B  = inv(self.B_I_B) @ (B_LDot_B - B_omega_IB @ B_L_B)
    

    def _recursiveForwardKinematics( self, nq, B_r_IB=[], A_IB=[], B_omega_B=[], B_v_B=[], B_omegaDot_B=[], B_a_B=[], B_J_S=[], B_J_R=[] ):
        '''
            Position and orientation, as well as velocities and accelerations are given by the parent 
            joint and passed in its call of 'recursiveForwardKinematics' 
        '''
        # root is the ground and has no dynamics
        if self.isRoot:
            self.A_IB = eye(3)
            self.B_omega_B = self.B_omegaDot_B = self.B_r_IB = self.B_v_B = self.B_a_B = zeros([3,1])
            self.B_J_S = self.B_J_R = zeros([3,nq])
        else:
            self.A_IB          = A_IB
            self.B_omega_B     = B_omega_B
            self.B_omegaDot_B  = B_omegaDot_B
            self.B_r_IB        = B_r_IB
            self.B_v_B         = B_v_B
            self.B_a_B         = B_a_B
            self.B_J_S         = B_J_S
            self.B_J_R         = B_J_R
        
        for childJoint in self.childJoints:
            childJoint._recursiveForwardKinematics(nq, self.B_r_IB, self.A_IB, self.B_omega_B, self.B_v_B, self.B_omegaDot_B, self.B_a_B,  self.B_J_S, self.B_J_R)


    def _recursiveComputationOfMfg( self ): # -> [M, f, g]
        '''
            This method requires a model update with all generalized accelerations set to zero
            such that B_a_B and B_omegaDot_B represent bias accelerations and not real accelerations
        '''
        # Compute the components for this body:
        M =   self.B_J_S.T * self.m_B    @ self.B_J_S + \
              self.B_J_R.T @ self.B_I_B  @ self.B_J_R  
        f = - self.B_J_S.T * self.m_B    @ self.B_a_B - \
              self.B_J_R.T @ (self.B_I_B @ self.B_omegaDot_B + skew(self.B_omega_B) @ self.B_I_B @ self.B_omega_B)
        g =   self.B_J_S.T @ self.A_IB.T @ self.I_grav * self.m_B + \
              self.B_J_R.T @ self.A_IB.T @ zeros([3,1]) 

        for childJoint in self.childJoints:
            M_part, f_part, g_part = childJoint.sucBody._recursiveComputationOfMfg()
            M += M_part
            f += f_part
            g += g_part
        return [M, f, g]


    ''' -------------------- GRAPHICS ------------------- '''

    def _recursiveInitGraphicsVPython(self):
        if not self.isRoot:   # for now, ground does not need a graphics representation
            # Inertia ellipse and principal axes
            self.ellsize, self.A_BP = self.getInertiaEllipsoid()
            # create Ellipse object in OPENGL
            self.ellipsoid = vellipsoid(pos=vector(0,0,0), color=color.orange, size=vector(*(self.ellsize*2)))
            # recursive call to other objects in the tree
        for childJoint in self.childJoints:
            childJoint.sucBody._recursiveInitGraphicsVPython()

    def _recursiveUpdateGraphicsVPython(self):
        if not self.isRoot:   # for now, ground does not need a graphics representation
            self.ellipsoid.pos = self.A_IB @ self.B_r_IB
            self.ellipsoid.orientation = self.A_IB @ self.A_BP
        # recursive call to other objects in the tree
        for childJoint in self.childJoints:
            childJoint.sucBody._recursiveUpdateGraphicsVPython()

    def getInertiaEllipsoid(self): # -> []
        '''
            returns:
                - A_BP: rotation matrix from principal axes to body coordinates
                - ellsize: vector with the 3 ellipse principal radius corresponding to the Inertia matrix
        '''
        # Compute the inertia axis:
        D, V = eig(self.B_I_B)

        A_BP = V

        I1, I2, I3 = D
        # Define the main axis of the ellipsoid:
        a = sqrt(2.5/self.m_B*(- I1 + I2 + I3))
        b = sqrt(2.5/self.m_B*(+ I1 - I2 + I3))
        c = sqrt(2.5/self.m_B*(+ I1 + I2 - I3))
        ellsize = array([a,b,c])

        return [ellsize, A_BP]



class Ground(RigidBody):
    def __init__(self):
        super().__init__(m_B=0, B_I_B=zeros([3,3]))


class Rod(RigidBody):
    def __init__( self, length=1, radius_o=0.01, radius_i=0, density=8000, I_grav=array([[0,0,-9.81]]).T ):
        self.length = length
        self.radius_i = radius_i
        self.radius_o = radius_o
        self.density = density
        volume = pi * (radius_o**2 - radius_i**2) * length
        mass = density * volume
        inertia = mass * diag([0.5*(radius_o**2 + radius_i**2) , 0.25*(radius_o**2 + radius_i**2 + length**2/3), 0.25*(radius_o**2 + radius_i**2 + length**2/3) ])
        super().__init__( m_B=mass, B_I_B=inertia, I_grav=I_grav )
    
    def _recursiveInitGraphicsVPython(self):
        if not self.isRoot:   # for now, ground does not need a graphics representation
            # create Ellipse object in OPENGL
            self.cylinder = cylinder(pos=vector(*(self.A_IB @ self.B_r_IB)), color=color.orange, axis=vector(self.length,0,0), radius=self.radius_o)
            # recursive call to other objects in the tree
        for childJoint in self.childJoints:
            childJoint.sucBody._recursiveInitGraphicsVPython()

    def _recursiveUpdateGraphicsVPython(self):
        if not self.isRoot:   # for now, ground does not need a graphics representation
            self.cylinder.pos  = vector( *(self.A_IB @ (self.B_r_IB - array([[self.length/2,0,0]]).T) ) )
            self.cylinder.axis = vector( *( self.A_IB[:,0] * self.length ) )
        # recursive call to other objects in the tree
        for childJoint in self.childJoints:
            childJoint.sucBody._recursiveUpdateGraphicsVPython()


class Ellipsoid(RigidBody):
    def __init__( self, rx=1, ry=0.01, rz=0, density=8000, I_grav=array([[0,0,-9.81]]).T ):
        # ellipsoid principal diameters
        self.rx = rx
        self.ry = ry
        self.rz = rz
        volume = 4/3 * pi * rx * ry * rz
        mass = density * volume
        inertia = mass/5 * diag([ry**2+rz**2, rx**2+rz**2, rx**2+ry**2])
        super().__init__( m_B=mass, B_I_B=inertia, I_grav=I_grav )