# Import third-party modules
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter

# Import modules specific to this package
from beam import Beam
from histogram_functions import histogram_cic_1d, histogram_cic_2d

"""
Module Name: df_tracker.py

Contains the DF_Tracker class
"""

class DF_Tracker():
    """
    Tracks the histogram and CSR meshes at all time steps along with all integrand related histograms
    """

    def __init__(self, total_steps, histo_mesh_params, csr_mesh_params, beam):
        """
        Initalizes the DF_Tracker, preallocates enough space in memory
        Parameters:
            total_steps: the total number of steps in the lattice
            histo_mesh_params: the parameters detailing the characteristics of the histogram meshes
            CSR_mesh_params: the parameters detailing the characteristics of the CSR_mesh_params
            beam: the initial beam object
        """
        self.total_steps = total_steps

        # Histogram and CSR mesh parameters
        self.h_params = histo_mesh_params
        self.csr_params = csr_mesh_params

        # CSR xz mesh coordinates for each step
        self.csr_coords_xz = np.empty((total_steps, self.csr_params["obins"], self.csr_params["pbins"], 2), dtype=np.float64)

        # Histogram and CSR y mesh coordinates (they are independent of step so we can populate here)
        h_bound = self.h_params["ylim"]*beam.init_std_y + beam.init_mean_y
        csr_bound = self.csr_params["ylim"]*beam.init_std_y + beam.init_mean_y
        self.h_coords_y = np.linspace(-h_bound, h_bound, self.h_params["ybins"])
        self.csr_coords_y = np.linspace(-csr_bound, csr_bound, self.csr_params["ybins"])

        # Histogram matrices
        self.t1_h = np.empty((total_steps, 2), dtype=np.float64)                # 1st tranform (in unit mesh)
        self.C_h = np.empty((total_steps, 2, 2), dtype=np.float64)              # Compression
        self.C_inv_h = np.empty((total_steps, 2, 2), dtype=np.float64)          # Compression inversion
        self.R_h = np.empty((total_steps, 2, 2), dtype=np.float64)              # Rotation
        self.R_inv_h = np.empty((total_steps, 2, 2), dtype=np.float64)          # Rotation inversion
        self.t2_h = np.empty((total_steps, 2), dtype=np.float64)                # 2nd tranform (to beam center)

        # CSR matrices
        self.t1_csr = np.empty((total_steps, 2), dtype=np.float64)              # 1st tranform (in unit mesh)
        self.C_csr = np.empty((total_steps, 2, 2), dtype=np.float64)            # Compression
        self.C_inv_csr = np.empty((total_steps, 2, 2), dtype=np.float64)        # Compression inversion
        self.R_csr = np.empty((total_steps, 2, 2), dtype=np.float64)            # Rotation
        self.R_inv_csr = np.empty((total_steps, 2, 2), dtype=np.float64)        # Rotation inversion
        self.t2_csr = np.empty((total_steps, 2), dtype=np.float64)              # 2nd tranform (to beam center)

        # std of the beam in the parallel and orthonormal directions in the xz plane for each step
        self.p_sd = np.empty(total_steps, dtype=np.float64)
        self.o_sd = np.empty(total_steps, dtype=np.float64)
        self.tilt_angle = np.empty(total_steps, dtype=np.float64)               # Tilt angle of beam at each step

        # The histograms themselves, we have 2 sets, one for the xz plane and one for y
        self.xz_density = np.empty((total_steps, self.h_params["obins"], self.h_params["pbins"]), dtype=np.float64)            # Density
        self.partial_density_x = np.empty((total_steps, self.h_params["obins"], self.h_params["pbins"]), dtype=np.float64)  # Partial Derivative of density wrt x
        self.partial_density_z = np.empty((total_steps, self.h_params["obins"], self.h_params["pbins"]), dtype=np.float64)  # Partial Derivative of density wrt x
        self.beta_x = np.empty((total_steps, self.h_params["obins"], self.h_params["pbins"]), dtype=np.float64)             # x component of beta = v/c
        self.partial_beta_x = np.empty((total_steps, self.h_params["obins"], self.h_params["pbins"]), dtype=np.float64)     # x component of partial beta

        # y histos
        self.y_density = np.empty((total_steps, self.h_params["ybins"]), dtype=np.float64)
        self.partial_density_y = np.empty((total_steps, self.h_params["ybins"]), dtype=np.float64)

    def populate_step(self, step_index, beam, update_CSR_mesh=True):
        """
        Given a beam object and a step index, populates all corresponding numpy array values
        """
        # Populate beam characteristics
        self.tilt_angle[step_index] = beam.get_tilt_angle()
        self.p_sd[step_index], self.o_sd[step_index] = beam.get_std_wrt_linear_fit(self.tilt_angle[step_index])

        # Popultate transformation matrices for histogram mesh (not in ij format)
        (self.t1_h[step_index],
         self.C_h[step_index],
         self.C_inv_h[step_index],
         self.R_h[step_index],
         self.R_inv_h[step_index],
         self.t2_h[step_index]) = self.get_mesh_matrices(self.h_params, beam, step_index)

        # Populate xz histogram density, beta_x, etc...
        (self.xz_density[step_index], 
         self.beta_x[step_index],
         self.partial_density_x[step_index],
         self.partial_density_z[step_index],
         self.partial_beta_x[step_index]) = self.populate_xz_histograms(beam.z, beam.x, beam.px, step_index)
        
        # Populate y histograms
        self.y_density[step_index] = self.populate_y_histograms(beam.y)

        # If we update the CSR_mesh we return it for quick computation
        if update_CSR_mesh:
            (self.t1_csr[step_index],
             self.C_csr[step_index],
             self.C_inv_csr[step_index],
             self.R_csr[step_index],
             self.R_inv_csr[step_index],
             self.t2_csr[step_index]) = self.get_mesh_matrices(self.csr_params, beam, step_index)

            # Populate CSR mesh coordinates
            self.csr_coords_xz[step_index] = self.get_xz_mesh_coordinates("csr", step_index)

            return self.csr_params, self.t2_csr[step_index], self.R_inv_csr[step_index], self.csr_coords_xz[step_index]
        
    def get_mesh_matrices(self, mesh_params, beam, step_index):
        """
        Given the mesh dimensions and the beam, creates the matrices which transform the mesh from coordinate space to cover the beam in z,x space
        """
        # Unpack the inputed dictionaries
        pbins, obins, plim, olim = mesh_params["pbins"], mesh_params["obins"], mesh_params["plim"], mesh_params["olim"]
        x_mean, z_mean, tilt_angle = beam.mean_x, beam.mean_z, self.tilt_angle[step_index]

        # Popultate transformation matrices (not in ij format)
        t1 = np.array([(pbins-1)/2, (obins-1)/2], dtype = np.float64)
        C = np.array([[2*(plim * self.p_sd[step_index])/(pbins-1), 0.0],
                      [0.0, 2*(olim * self.o_sd[step_index])/(obins-1)]], dtype = np.float64)
        C_inv = np.linalg.inv(C)
        R = np.array([[np.cos(tilt_angle), -np.sin(tilt_angle)],
                      [np.sin(tilt_angle), np.cos(tilt_angle)]], dtype=np.float64)
        R_inv = np.linalg.inv(R)
        t2 = np.array([z_mean,x_mean], dtype=np.float64)

        return t1, C, C_inv, R, R_inv, t2
    
    def get_xz_mesh_coordinates(self, type, step_index):
        """
        Creates a rotated and compressed xz mesh to match what ever the beam distribution looks like at this step
        Helper function to populate, populates the mesh coordinates. Also is used to create the mesh upon which 
        the CSR wake is computed.
        Parameters:
            type: string, either 'histogram' or 'csr'
        Returns:
            mesh_coords: the coordinates of the mesh in ij format
        """
        if type == "histogram":
            pbins, obins = self.h_params["pbins"], self.h_params["obins"]
            t1, C, R, t2 = self.t1_h[step_index], self.C_h[step_index], self.R_h[step_index], self.t2_h[step_index]

        elif type == "csr":
            pbins, obins = self.csr_params["pbins"], self.csr_params["obins"]
            t1, C, R, t2 = self.t1_csr[step_index], self.C_csr[step_index], self.R_csr[step_index], self.t2_csr[step_index]
        else:
            print("error incorrect type given")

        # Seed the mesh
        mesh_z = np.arange(pbins)
        mesh_x = np.arange(obins)

        Z, X = np.meshgrid(mesh_z, mesh_x)
        mesh_coords_list = np.stack((Z.flatten(), X.flatten()), axis=0).T

        # Shift mesh to center
        mesh_coords_list = mesh_coords_list - t1
        
        # Compress mesh
        mesh_coords_list = mesh_coords_list @ C.T

        # Rotate mesh
        mesh_coords_list = mesh_coords_list @ R.T

        # Translate mesh to center of beam distribution
        mesh_coords_list = mesh_coords_list + t2

        # Populate the mesh coordinates in ij format
        mesh_coords = np.empty((obins, pbins, 2), dtype=np.float64)
        mesh_coords[:,:,0] = mesh_coords_list[:, 1].reshape(obins, pbins)
        mesh_coords[:,:,1] = mesh_coords_list[:, 0].reshape(obins, pbins)

        return mesh_coords
    
    def populate_xz_histograms(self, q1, q2, px, step_index):
        """
        Populates the density, velocity, etc histograms simultaneously for quick runtime
        Parameters:
            q1: 1st dimension's coords (must be z)
            q2: 2nd dimension's coords (must be x)
            px: the momentum of each particle
            step_index: the step index of the histogram to populate
        Returns:
            density, beta_x, partial_density_x, partial_density_z, partial_beta_x
        """
        # Unpack h_params dict
        pbins, obins, plim, olim, filter_order, filter_window, velocity_threshold = (
            self.h_params["pbins"],
            self.h_params["obins"],
            self.h_params["plim"],
            self.h_params["olim"],
            self.h_params["filter_order"],
            self.h_params["filter_window"],
            self.h_params["velocity_threshold"])
        
        R, R_inv, t2 = self.R_h[step_index], self.R_inv_h[step_index], self.t2_h[step_index]

        p_sd = self.p_sd[step_index]
        o_sd = self.o_sd[step_index]

        # Put the beam macro particle positions in the space where the grid is rotated
        particle_positions = (((np.stack((q1, q2))).T - t2) @ R_inv.T)

        # Create density histogram (note that we have to transfer the particle_positions to ij again)
        density = histogram_cic_2d(particle_positions[:,1], particle_positions[:,0], np.ones(particle_positions[:,1].shape), obins, -olim*o_sd, olim*o_sd, pbins, -plim*p_sd, plim*p_sd)

        # Create a 2D DF velocity (x compononet only) distribution histogram
        beta_x = histogram_cic_2d(particle_positions[:,1], particle_positions[:,0], px, obins, -olim*o_sd, olim*o_sd, pbins, -plim*p_sd, plim*p_sd)
 
        # The minimum particle number of particles in a bin for that bin to have non zero beta_x value
        threshold = np.max(density) / (velocity_threshold)

        # Make each mesh element value be equal to the AVERAGE velocity of particles in said element
        # Only for bins with particle density above the threshold
        beta_x[density > threshold] /= density[density > threshold]

        # Smooth density and velocity function using 2D Savitzky-Golay filter
        density = savgol_filter(savgol_filter(x = density, window_length=filter_window, polyorder=filter_order, axis = 0), window_length=filter_window, polyorder=filter_order, axis=1)
        beta_x = savgol_filter(savgol_filter(x = beta_x, window_length=filter_window, polyorder=filter_order, axis = 0), window_length=filter_window, polyorder=filter_order, axis=1)

        # Integrate the density function over the integration space using trapezoidal rule
        o_dim = np.linspace(-olim*o_sd, olim*o_sd, obins)
        p_dim = np.linspace(-plim*p_sd, plim*p_sd, pbins)
        dsum = np.trapz(np.trapz(density, o_dim, axis=0), p_dim, axis=0)

        # Normalize the density distirbution historgram
        density /= dsum

        # Set beta_x = 0 for all bins with low particle count
        beta_x[density <= threshold] = 0

        # Create the histograms for the partial density wrt x and wrt z
        partial_density_o, partial_density_p = np.gradient(density, o_dim, p_dim)

        # Create the histograms for the partial beta_x wrt x
        partial_beta_o, partial_beta_p = np.gradient(beta_x, o_dim, p_dim)

        # Apply 2D Savitzky-Golay to position and velocity gradient histograms
        partial_density_o = savgol_filter(savgol_filter(x = partial_density_o, window_length=filter_window, polyorder=filter_order, axis = 0), window_length=filter_window, polyorder=filter_order, axis=1)
        partial_density_p = savgol_filter(savgol_filter(x = partial_density_p, window_length=filter_window, polyorder=filter_order, axis = 0), window_length=filter_window, polyorder=filter_order, axis=1)
        partial_beta_o = savgol_filter(savgol_filter(x = partial_beta_o, window_length=filter_window, polyorder=filter_order, axis = 0), window_length=filter_window, polyorder=filter_order, axis=1)
        partial_beta_p = savgol_filter(savgol_filter(x = partial_beta_p, window_length=filter_window, polyorder=filter_order, axis = 0), window_length=filter_window, polyorder=filter_order, axis=1)

        # Again filter out the low populated bins
        threshold = np.max(density) / velocity_threshold * 8
        partial_beta_o[density < threshold] = np.mean(partial_beta_o[density > threshold])
        partial_beta_p[density < threshold] = np.mean(partial_beta_p[density > threshold])

        # Filter out the low populated bins in partial density
        partial_density_o[density < threshold] = 0
        partial_density_p[density < threshold] = 0

        # The histograms computed via the gradient function need to be put into x and z
        partial_density = np.dstack((partial_density_p, partial_density_o))
        partial_beta = np.dstack((partial_beta_p, partial_beta_o))

        n,m,_ = partial_density.shape
        partial_density = partial_density.reshape(-1,2)
        partial_beta = partial_beta.reshape(-1,2)

        # Use transform to convert o and p to z and x DO NOT USE t2
        partial_density = (partial_density) @ R.T
        partial_beta = (partial_beta) @ R.T

        partial_density_x = partial_density[:,1].reshape(n,m)
        partial_density_z = partial_density[:,0].reshape(n,m)

        partial_beta_x = partial_beta[:,1]
        partial_beta_x = partial_beta_x.reshape(n,m)

        return density, beta_x, partial_density_x, partial_density_z, partial_beta_x
    
    def populate_y_histograms(self, q3):
        """
        Populates the y histograms for the indicated step
        Parameters:
            q3: 3rd dimensions coords (must be y)
            step_index: the step index of the histogram to populate
        Returns:
            y_density: the y dimension's histograms
        """
        ybins = self.h_params["ybins"]

        # Unpack h_params dict
        ybins, filter_order, filter_window, velocity_threshold = (
            self.h_params["ybins"],
            self.h_params["filter_order"],
            self.h_params["filter_window"],
            self.h_params["velocity_threshold"])
        
        # Populate y density histogram and apply Savitzky-Golay filter
        y_density = histogram_cic_1d(q3, np.ones(len(q3)), ybins, self.h_coords_y[0], self.h_coords_y[-1])
        y_density = savgol_filter(x = y_density, window_length=filter_window, polyorder=filter_order, axis = 0)

        # Normalize density
        dsum = np.trapz(y_density, self.h_coords_y)
        y_density /= dsum

        return y_density
    
    def plot_beam(self, step_index):
        """
        Plots each histogram at the inputed step_index to give a overview of what the beam looks like
        """
        fig, axes = plt.subplots(nrows=2, ncols=3, figsize=(12, 6))  # Adjust nrows and ncols as needed
        axes = axes.flatten()

        coords = self.get_xz_mesh_coordinates("histogram", step_index)
        Z = coords[:, :, 1]
        X = coords[:, :, 0]

        im1 = axes[0].pcolormesh(Z, X, self.xz_density[step_index], shading='auto', cmap='viridis')
        fig.colorbar(im1, ax=axes[0])
        axes[0].set_aspect("equal")
        axes[0].set_title("density")

        im2 = axes[1].pcolormesh(Z, X, self.beta_x[step_index], shading='auto', cmap='viridis')
        fig.colorbar(im2, ax=axes[1])
        axes[1].set_aspect("equal")
        axes[1].set_title("beta_x")

        im3 = axes[2].pcolormesh(Z, X, self.partial_density_x[step_index], shading='auto', cmap='viridis')
        fig.colorbar(im3, ax=axes[2])
        axes[2].set_aspect("equal")
        axes[2].set_title("parital_density_x")

        im4 = axes[3].pcolormesh(Z, X, self.partial_density_z[step_index], shading='auto', cmap='viridis')
        fig.colorbar(im4, ax=axes[3])
        axes[3].set_aspect("equal")
        axes[3].set_title("partial_density_z")

        im5 = axes[4].pcolormesh(Z, X, self.partial_beta_x[step_index], shading='auto', cmap='viridis')
        fig.colorbar(im5, ax=axes[4])
        axes[4].set_aspect("equal")
        axes[4].set_title("partial_beta_x")

        # Adjust layout to fit everything nicely
        plt.tight_layout()
        plt.show()

    def plot_xz_histogram(self, histo_vals, step_index, title=""):
        """
        Just plots the inputed histogram vals at the inputed step on a colormesh, very simple
        """
        Z = self.h_coords_xz[step_index][:, :, 1]
        X = self.h_coords_xz[step_index][:, :, 0]

        plt.pcolormesh(Z, X, histo_vals)

        # Add labels for the axes
        plt.xlabel('Z axis')
        plt.ylabel('X axis')

        # Add a color bar to show the scale of histo_vals
        plt.colorbar()

        # Add a title to the plot
        plt.title(title)

        # Display the plot
        plt.show()

    def plot_y_histograms(self, step_index, title=""):
        """
        Plots density_y and partial_density_y as two plots in the same figure
        """
        # Create a figure and two subplots (1 row, 2 columns)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

        # Plot y1 vs. x in the first subplot
        ax1.plot(self.h_coords_y, self.y_density[step_index], 'b-')
        ax1.set_xlabel('y')
        ax1.set_ylabel('y_density')
        ax1.set_title('y_density')
        ax1.legend()

        # Plot y2 vs. x in the second subplot
        ax2.plot(self.h_coords_y, self.partial_density_y[step_index], 'r-')
        ax2.set_xlabel('y')
        ax2.set_ylabel('partial_density_y')
        ax2.set_title('partial_density_y')
        ax2.legend()

        # Add a title to the entire figure
        fig.suptitle('y histograms at step '+str(step_index), fontsize=16)

        # Adjust layout to prevent overlap
        plt.tight_layout(rect=[0, 0, 1, 0.95])  # Adjust rect to make room for the suptitle

        # Show the plot
        plt.show()
    
    def plot_grid_transformation(self, beam, step_index, fig=None, ax=None, title=""):
        """
        Plots the mesh ontop of the beam distribution
        """
        new_fig = False
        if fig is None or ax is None:
            fig, ax = plt.subplots()
            new_fig = True

        X = self.h_coords_xz[step_index, :, :, 0]
        Z = self.h_coords_xz[step_index, :, :, 1]
        
        #Plot the mesh grid
        self.plot_mesh(ax, Z, X, "blue")

        # Plot the beam
        ax.scatter(beam.z, beam.x, color="red", s=10, label="Beam Distribution")

        # Plot the line of best fit
        z_end = self.h_params["plim"]*self.p_sd[step_index] * np.cos(self.tilt_angle[step_index])
        x_end = self.h_params["plim"]*self.p_sd[step_index] * np.sin(self.tilt_angle[step_index])
        #ax.plot([-z_end, z_end], [-x_end, x_end], color="black", linewidth = 2, label = "line of best fit")

        # Plot the line orthonormal to the line of best fit
        z_end = self.h_params["olim"]*self.o_sd[step_index] * np.cos(self.tilt_angle[step_index] + np.pi/2)
        x_end = self.h_params["olim"]*self.o_sd[step_index] * np.sin(self.tilt_angle[step_index] + np.pi/2)
        #ax.plot([-z_end, z_end], [-x_end, x_end], color="purple", linewidth=2, label="Line Ortho to Best Fit")

        if title == "":
            title = "Scatter Plot of Beam Distribution with Mesh Overlay"

        if new_fig:
            ax.set_title(title)
            ax.set_xlabel("z")
            ax.set_ylabel("x")
            ax.axis("equal")
            ax.legend()
            
            plt.show()

    def plot_particle_transformation(self, beam, step_index, fig=None, ax=None, title=""):
        """
        Plots the beam distribution in the mesh coordinate space, used to confirm that the transformations
        are correct.
        """
        new_fig = False
        if fig is None or ax is None:
            fig, ax = plt.subplots()
            new_fig = True

        particle_positions = (((np.stack((beam.z, beam.x))).T - self.t2_h[step_index]) @ self.R_inv_h[step_index].T)

        # Unpack h_params dict
        pbins, obins, plim, olim = (
            self.h_params["pbins"],
            self.h_params["obins"],
            self.h_params["plim"],
            self.h_params["olim"])
        
        p_sd = self.p_sd[step_index]
        o_sd = self.o_sd[step_index]

        o_dim = np.linspace(-olim*o_sd, olim*o_sd, obins)
        p_dim = np.linspace(-plim*p_sd, plim*p_sd, pbins)

        Z, X = np.meshgrid(p_dim, o_dim)
        
        #Plot the mesh grid
        self.plot_mesh(ax, Z, X, "blue")

        # Plot the beam
        ax.scatter(particle_positions[:,0], particle_positions[:,1], color="red", s=10, label="Beam Distribution")

        # Plot the line of best fit
        z_end = self.h_params["plim"]*self.p_sd[step_index] * np.cos(self.tilt_angle[step_index])
        x_end = self.h_params["plim"]*self.p_sd[step_index] * np.sin(self.tilt_angle[step_index])
        #ax.plot([-z_end, z_end], [-x_end, x_end], color="black", linewidth = 2, label = "line of best fit")

        # Plot the line orthonormal to the line of best fit
        z_end = self.h_params["olim"]*self.o_sd[step_index] * np.cos(self.tilt_angle[step_index] + np.pi/2)
        x_end = self.h_params["olim"]*self.o_sd[step_index] * np.sin(self.tilt_angle[step_index] + np.pi/2)
        #ax.plot([-z_end, z_end], [-x_end, x_end], color="purple", linewidth=2, label="Line Ortho to Best Fit")

        if title == "":
            title = "Scatter Plot of Beam Distribution with Mesh Overlay"

        if new_fig:
            ax.set_title(title)
            ax.set_xlabel("z")
            ax.set_ylabel("x")
            ax.axis("equal")
            ax.legend()
            
            plt.show()        

    def plot_mesh(self, ax, Z, X, color='black'):
        """
        Plots the inputed mesh on the inputed axis
        """
        # Plot vertical grid lines (lines along X)
        for i in range(X.shape[1]):
            ax.plot(Z[:, i], X[:, i], color, linewidth=1.0)

        # Plot horizontal grid lines (lines along Y)
        for j in range(X.shape[0]):
            ax.plot(Z[j, :], X[j, :], color, linewidth=1.0)