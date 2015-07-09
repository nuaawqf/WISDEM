#!/usr/bin/env python
# encoding: utf-8
"""
turbine.py

Created by Andrew Ning and Katherine Dykes on 2014-01-13.
Copyright (c) NREL. All rights reserved.
"""

from openmdao.main.api import Assembly, Component
from openmdao.main.datatypes.api import Float, Array, Enum, Bool, Int
from openmdao.lib.drivers.api import FixedPointIterator
import numpy as np

#from rotorse.rotor import RotorSE
#from towerse.tower import TowerSE
#from commonse.rna import RNAMass, RotorLoads
from drivewpact.drive import DriveWPACT
from drivewpact.hub import HubWPACT
from commonse.csystem import DirectionVector
from commonse.utilities import interp_with_deriv, hstack, vstack
from drivese.drive import Drive4pt, Drive3pt
from drivese.drivese_utils import blade_moment_transform, blade_force_transform
from drivese.hub import HubSE, Hub_System_Adder_drive

from SEAMLoads.SEAMLoads import SEAMLoads
from SEAMTower.SEAMTower import SEAMTower
from SEAMAero.SEAM_AEP import SEAMAEP
from SEAMRotor.SEAMRotor import SEAMRotor
# from SEAMGeometry.SEAMGeometry import SEAMGeometry

def connect_io(top, cls):

    cls_name = cls.name
    for name in cls.list_inputs():

        try:
            top.connect(name, cls_name + '.%s' % name)
        except:
            # print 'failed connecting', cls_name, name
            pass

    for name in cls.list_outputs():
        try:
            top.connect(cls_name + '.%s' % name, name)
        except:
            pass


def configure_turbine(assembly, with_new_nacelle=True, flexible_blade=False, with_3pt_drive=False):
    """a stand-alone configure method to allow for flatter assemblies

    Parameters
    ----------
    assembly : Assembly
        an openmdao assembly to be configured
    with_new_nacelle : bool
        False uses the default implementation, True uses an experimental implementation designed
        to smooth out discontinities making in amenable for gradient-based optimization
    flexible_blade : bool
        if True, internally solves the coupled aero/structural deflection using fixed point iteration.
        Note that the coupling is currently only in the flapwise deflection, and is primarily
        only important for highly flexible blades.  If False, the aero loads are passed
        to the structure but there is no further iteration.
    """

    #SEAM variables ----------------------------------
    #d2e = Float(0.73, iotype='in', desc='Dollars to Euro ratio'
    assembly.add('rated_power',Float(3., iotype='in', units='MW', desc='Turbine rated power'))
    #hub_height = Float(100., iotype='in', units='m', desc='Hub height')
    #rotor_diameter = Float(110., iotype='in', units='m', desc='Rotor diameter')
    assembly.add('site_type',Enum('onshore', values=('onshore', 'offshore'), iotype='in', desc='Site type: onshore or offshore'))
    #tower_cost_per_mass = Float(4.0, iotype='in', desc='Tower cost per mass')
    #blade_cost_per_mass = Float(15., iotype='in', desc='Blade cost per mass')
    #hub_cost_per_mass = Float(3.5, iotype='in', desc='Hub cost per mass')
    #spinner_cost_per_mass = Float(4.5, iotype='in', desc='Spinner cost per mass')
    #bearing_cost_per_mass = Float(14.0, iotype='in', desc='Bearing cost per mass')

    #turbine_cost = Float(iotype='out', desc='Total turbine CAPEX')
    #infra_cost = Float(iotype='out', desc='Total infrastructure CAPEX')
    #total_cost = Float(iotype='out', desc='Total CAPEX')

    assembly.add('rho_steel', Float(7.8e3, iotype='in', desc='density of steel'))
    assembly.add('D_bottom', Float(4., iotype='in', desc='Tower bottom diameter'))
    assembly.add('D_top', Float(2., iotype='in', desc='Tower top diameter'))

    assembly.add('Neq', Float(1.e7, iotype='in', desc=''))
    assembly.add('Slim_ext', Float(235., iotype='in', units='MPa', desc=''))
    assembly.add('Slim_fat', Float(14.885, iotype='in', units='MPa', desc=''))
    assembly.add('SF_tower', Float(1.5, iotype='in', desc=''))
    assembly.add('PMtarget', Float(1., iotype='in', desc=''))
    assembly.add('WohlerExpTower', Float(4., iotype='in', desc=''))

    assembly.add('height', Array(iotype='out', desc='Tower discretization'))
    assembly.add('t', Array(iotype='out', desc='Wall thickness'))
    assembly.add('mass', Float(iotype='out', desc='Tower mass'))

    assembly.add('tsr', Float(iotype='in', units='m', desc='Design tip speed ratio'))
    assembly.add('F', Float(iotype='in', desc=''))
    assembly.add('WohlerExpFlap', Float(iotype='in', desc='Wohler Exponent blade flap'))
    assembly.add('WohlerExpTower', Float(iotype='in', desc='Wohler Exponent tower bottom'))
    assembly.add('nSigma4fatFlap', Float(iotype='in', desc=''))
    assembly.add('nSigma4fatTower',  Float(iotype='in', desc=''))
    assembly.add('dLoaddUfactorFlap', Float(iotype='in', desc=''))
    assembly.add('dLoaddUfactorTower', Float(iotype='in', desc=''))
    assembly.add('Neq', Float(iotype='in', desc=''))
    assembly.add('EdgeExtDynFact', Float(iotype='in', desc=''))
    assembly.add('EdgeFatDynFact', Float(iotype='in', desc=''))

    assembly.add('max_tipspeed', Float(iotype='in', desc='Maximum tip speed'))
    assembly.add('n_wsp', Int(iotype='in', desc='Number of wind speed bins'))
    assembly.add('min_wsp', Float(0.0, iotype = 'in', units = 'm/s', desc = 'min wind speed'))
    assembly.add('max_wsp', Float(iotype = 'in', units = 'm/s', desc = 'max wind speed'))

    #Iref = Float(iotype='in', desc='Reference turbulence intensity')
    #WeibullInput = Bool(iotype='in', desc='Flag for Weibull input')
    #WeiA_input = Float(iotype = 'in', units='m/s', desc = 'Weibull A')
    #WeiC_input = Float(iotype = 'in', desc='Weibull C')
    #NYears = Float(iotype = 'in', desc='Operating years')

    assembly.add('overallMaxTower', Float(iotype='out', units='kN*m', desc='Max tower bottom moment'))
    assembly.add('overallMaxFlap', Float(iotype='out', units='kN*m', desc='Max blade root flap moment'))
    assembly.add('FlapLEQ', Float(iotype='out', units='kN*m', desc='Blade root flap lifetime eq. moment'))
    assembly.add('TowerLEQ', Float(iotype='out', units='kN*m', desc='Tower bottom lifetime eq. moment'))

    assembly.add('Nsections', Int(iotype='in', desc='number of sections'))
    assembly.add('Neq', Float(1.e7, iotype='in', desc=''))

    assembly.add('WohlerExpFlap', Float(iotype='in', desc=''))
    assembly.add('PMtarget', Float(iotype='in', desc=''))

    #rotor_diameter = Float(iotype='in', units='m', desc='') #[m]
    assembly.add('MaxChordrR', Float(iotype='in', units='m', desc='')) #[m]

    assembly.add('OverallMaxFlap', Float(iotype='in', desc=''))
    assembly.add('OverallMaxEdge', Float(iotype='in', desc=''))
    assembly.add('TIF_FLext', Float(iotype='in', desc='')) # Tech Impr Factor _ flap extreme
    assembly.add('TIF_EDext', Float(iotype='in', desc=''))

    assembly.add('FlapLEQ', Float(iotype='in', desc=''))
    assembly.add('EdgeLEQ', Float(iotype='in', desc=''))
    assembly.add('TIF_FLfat', Float(iotype='in', desc=''))

    assembly.add('sc_frac_flap', Float(iotype='in', desc='')) # sparcap fraction of chord flap
    assembly.add('sc_frac_edge', Float(iotype='in', desc='')) # sparcap fraction of thickness edge

    assembly.add('SF_blade', Float(iotype='in', desc='')) #[factor]
    assembly.add('Slim_ext_blade', Float(iotype='in', units='MPa', desc=''))
    assembly.add('Slim_fat_blade', Float(iotype='in', units='MPa', desc=''))

    assembly.add('AddWeightFactorBlade', Float(iotype='in', desc='')) # Additional weight factor for blade shell
    assembly.add('BladeDens', Float(iotype='in', units='kg/m**3', desc='density of blades')) # [kg / m^3]
    #BladeCostPerMass = Float(iotype='in', desc='') #[e/kg]
    #HubCostPerMass = Float(iotype='in', desc='') #[e/kg]
    #SpinnerCostPerMass = Float(iotype='in', desc='') #[e/kg]

    assembly.add('BladeWeight', Float(iotype = 'out', units = 'kg', desc = 'BladeMass' ))

    assembly.add('mean_wsp', Float(iotype = 'in', units = 'm/s', desc = 'mean wind speed')  )  # [m/s]
    assembly.add('air_density', Float(iotype = 'in', units = 'kg/m**3', desc = 'density of air')) # [kg / m^3]
    assembly.add('turbulence_int', Float(iotype = 'in', desc = ''))
    assembly.add('max_Cp', Float(iotype = 'in', desc = 'max CP'))
    assembly.add('gearloss_const', Float(iotype = 'in', desc = 'Gear loss constant'))
    assembly.add('gearloss_var', Float(iotype = 'in', desc = 'Gear loss variable'))
    assembly.add('genloss', Float(iotype = 'in', desc = 'Generator loss'))
    assembly.add('convloss', Float(iotype = 'in', desc = 'Converter loss'))

    # Outputs
    assembly.add('rated_wind_speed', Float(units = 'm / s', iotype='out', desc='wind speed for rated power'))
    assembly.add('ideal_power_curve', Array(iotype='out', units='kW', desc='total power before losses and turbulence'))
    assembly.add('power_curve', Array(iotype='out', units='kW', desc='total power including losses and turbulence'))
    assembly.add('wind_curve', Array(iotype='out', units='m/s', desc='wind curve associated with power curve'))

    #NYears = Float(iotype = 'in', desc='Operating years')  # move this to COE calculation

    #aep = Float(iotype = 'out', units='mW*h', desc='Annual energy production in mWh')
    #total_aep = Float(iotype = 'out', units='mW*h', desc='AEP for total years of production')

    # END SEAM Variables ----------------------

    # Add SEAM components and connections
    assembly.add('loads', SEAMLoads())
    assembly.add('tower_design', SEAMTower(21))
    assembly.add('blade_design', SEAMRotor())
    assembly.add('aep_calc', SEAMAEP())
    assembly.driver.workflow.add(['loads', 'tower_design', 'blade_design', 'aep_calc'])

    assembly.connect('loads.overallMaxTower', 'tower_design.overallMaxTower')
    assembly.connect('loads.TowerLEQ', 'tower_design.TowerLEQ')

    assembly.connect('loads.overallMaxFlap', 'blade_design.overallMaxFlap')
    assembly.connect('loads.overallMaxEdge', 'blade_design.overallMaxEdge')
    assembly.connect('loads.FlapLEQ', 'blade_design.FlapLEQ')
    assembly.connect('loads.EdgeLEQ', 'blade_design.EdgeLEQ')

    connect_io(assembly, assembly.aep_calc)
    connect_io(assembly, assembly.loads)
    connect_io(assembly, assembly.tower_design)
    connect_io(assembly, assembly.blade_design)

    # End SEAM add components and connections -------------

    # --- general turbine configuration inputs---
    assembly.add('rho', Float(1.225, iotype='in', units='kg/m**3', desc='density of air', deriv_ignore=True))
    assembly.add('mu', Float(1.81206e-5, iotype='in', units='kg/m/s', desc='dynamic viscosity of air', deriv_ignore=True))
    assembly.add('shear_exponent', Float(0.2, iotype='in', desc='shear exponent', deriv_ignore=True))
    assembly.add('hub_height', Float(90.0, iotype='in', units='m', desc='hub height'))
    assembly.add('turbine_class', Enum('I', ('I', 'II', 'III', 'IV'), iotype='in', desc='IEC turbine class'))
    assembly.add('turbulence_class', Enum('B', ('A', 'B', 'C'), iotype='in', desc='IEC turbulence class class'))
    assembly.add('g', Float(9.81, iotype='in', units='m/s**2', desc='acceleration of gravity', deriv_ignore=True))
    assembly.add('cdf_reference_height_wind_speed', Float(90.0, iotype='in', desc='reference hub height for IEC wind speed (used in CDF calculation)'))
    assembly.add('downwind', Bool(False, iotype='in', desc='flag if rotor is downwind'))
    assembly.add('tower_d', Array([0.0], iotype='in', units='m', desc='diameters along tower'))
    assembly.add('generator_speed', Float(iotype='in', units='rpm', desc='generator speed'))
    assembly.add('machine_rating', Float(5000.0, units='kW', iotype='in', desc='machine rated power'))
    assembly.add('rna_weightM', Bool(True, iotype='in', desc='flag to consider or not the RNA weight effect on Moment'))

    if with_new_nacelle:
        assembly.add('hub',HubSE())
        assembly.add('hubSystem',Hub_System_Adder_drive())
        assembly.add('moments',blade_moment_transform())
        assembly.add('forces',blade_force_transform())
        if with_3pt_drive:
            assembly.add('nacelle', Drive3pt())
        else:
            assembly.add('nacelle', Drive4pt())
    else:
        assembly.add('nacelle', DriveWPACT())
        assembly.add('hub', HubWPACT())

    assembly.driver.workflow.add(['hub', 'nacelle'])
    if with_new_nacelle:
        assembly.driver.workflow.add(['hubSystem','moments','forces'])

    # connections to hub and hub system
    assembly.connect('blade_design.BladeWeight', 'hub.blade_mass')
    assembly.connect('loads.overallMaxFlap', 'hub.rotor_bending_moment')
    assembly.connect('rotor_diameter', ['hub.rotor_diameter'])
    #assembly.connect('rotor.hub_diameter', 'hub.blade_root_diameter')
    #assembly.connect('rotor.nBlades', 'hub.blade_number')
    if with_new_nacelle:
        assembly.connect('rotor_diameter', ['hubSystem.rotor_diameter'])
        assembly.connect('nacelle.MB1_location','hubSystem.MB1_location') # TODO: bearing locations
        assembly.connect('nacelle.L_rb','hubSystem.L_rb')
        #assembly.connect('rotor.tilt','hubSystem.shaft_angle')
        assembly.connect('hub.hub_diameter','hubSystem.hub_diameter')
        assembly.connect('hub.hub_thickness','hubSystem.hub_thickness')
        assembly.connect('hub.hub_mass','hubSystem.hub_mass')
        assembly.connect('hub.spinner_mass','hubSystem.spinner_mass')
        assembly.connect('hub.pitch_system_mass','hubSystem.pitch_system_mass')

    # connections to nacelle #TODO: fatigue option variables
    assembly.connect('rotor_diameter', 'nacelle.rotor_diameter')
    #assembly.connect('1.5 * rotor.ratedConditions.Q', 'nacelle.rotor_torque')
    #assembly.connect('rotor.ratedConditions.T', 'nacelle.rotor_thrust')
    #assembly.connect('rotor.ratedConditions.Omega', 'nacelle.rotor_speed')
    assembly.connect('rated_power', 'nacelle.machine_rating')
    #assembly.connect('rotor.root_bending_moment', 'nacelle.rotor_bending_moment')
    #assembly.connect('generator_speed/rotor.ratedConditions.Omega', 'nacelle.gear_ratio')
    #assembly.connect('tower_d[-1]', 'nacelle.tower_top_diameter')  # OpenMDAO circular dependency issue
    #assembly.connect('rotor.mass_all_blades + hub.hub_system_mass', 'nacelle.rotor_mass') # assuming not already in rotor force / moments
    # variable connections for new nacelle
    if with_new_nacelle:
        #assembly.connect('rotor.nBlades','nacelle.blade_number')
        #assembly.connect('rotor.tilt','nacelle.shaft_angle')
        assembly.connect('333.3 * rated_power / 1000.0','nacelle.shrink_disc_mass')
        #assembly.connect('rotor.hub_diameter','nacelle.blade_root_diameter')

        #moments
        # assembly.connect('rotor.Q_extreme','nacelle.rotor_bending_moment_x')
        #assembly.connect('rotor.Mxyz_0','moments.b1')
        #assembly.connect('rotor.Mxyz_120','moments.b2')
        #assembly.connect('rotor.Mxyz_240','moments.b3')
        #assembly.connect('rotor.Pitch','moments.pitch_angle')
        #assembly.connect('rotor.TotalCone','moments.cone_angle')
        #assembly.connect('moments.Mx','nacelle.rotor_bending_moment_x') #accounted for in ratedConditions.Q
        #assembly.connect('moments.My','nacelle.rotor_bending_moment_y')
        #assembly.connect('moments.Mz','nacelle.rotor_bending_moment_z')

        #forces
        # assembly.connect('rotor.T_extreme','nacelle.rotor_force_x')
        #assembly.connect('rotor.Fxyz_0','forces.b1')
        #assembly.connect('rotor.Fxyz_120','forces.b2')
        #assembly.connect('rotor.Fxyz_240','forces.b3')
        #assembly.connect('rotor.Pitch','forces.pitch_angle')
        #assembly.connect('rotor.TotalCone','forces.cone_angle')
        #assembly.connect('forces.Fx','nacelle.rotor_force_x')
        #assembly.connect('forces.Fy','nacelle.rotor_force_y')
        #assembly.connect('forces.Fz','nacelle.rotor_force_z')


class TurbineSE(Assembly):

    def configure(self):
        configure_turbine(self)


if __name__ == '__main__':

    turbine = TurbineSE()
    turbine.sea_depth = 0.0 # 0.0 for land-based turbine
    wind_class = 'I'

    #from wisdem.reference_turbines.nrel5mw.nrel5mw import configure_nrel5mw_turbine
    #configure_nrel5mw_turbine(turbine,wind_class,turbine.sea_depth)

    # === Turbine ===
    turbine.rho = 1.225  # (Float, kg/m**3): density of air
    turbine.mu = 1.81206e-5  # (Float, kg/m/s): dynamic viscosity of air
    turbine.shear_exponent = 0.2  # (Float): shear exponent
    turbine.hub_height = 90.0  # (Float, m): hub height
    turbine.turbine_class = 'I'  # (Enum): IEC turbine class
    turbine.turbulence_class = 'B'  # (Enum): IEC turbulence class class
    turbine.cdf_reference_height_wind_speed = 90.0  # (Float): reference hub height for IEC wind speed (used in CDF calculation)
    turbine.g = 9.81  # (Float, m/s**2): acceleration of gravity
    # ======================


    # === nacelle ======
    turbine.nacelle.L_ms = 1.0  # (Float, m): main shaft length downwind of main bearing in low-speed shaft
    turbine.nacelle.L_mb = 2.5  # (Float, m): main shaft length in low-speed shaft

    turbine.nacelle.h0_front = 1.7  # (Float, m): height of Ibeam in bedplate front
    turbine.nacelle.h0_rear = 1.35  # (Float, m): height of Ibeam in bedplate rear

    turbine.nacelle.drivetrain_design = 'geared'
    turbine.nacelle.crane = True  # (Bool): flag for presence of crane
    turbine.nacelle.bevel = 0  # (Int): Flag for the presence of a bevel stage - 1 if present, 0 if not
    turbine.nacelle.gear_configuration = 'eep'  # (Str): tring that represents the configuration of the gearbox (stage number and types)

    turbine.nacelle.Np = [3, 3, 1]  # (Array): number of planets in each stage
    turbine.nacelle.ratio_type = 'optimal'  # (Str): optimal or empirical stage ratios
    turbine.nacelle.shaft_type = 'normal'  # (Str): normal or short shaft length
    #turbine.nacelle.shaft_angle = 5.0  # (Float, deg): Angle of the LSS inclindation with respect to the horizontal
    turbine.nacelle.shaft_ratio = 0.10  # (Float): Ratio of inner diameter to outer diameter.  Leave zero for solid LSS
    turbine.nacelle.carrier_mass = 8000.0 # estimated for 5 MW
    turbine.nacelle.mb1Type = 'CARB'  # (Str): Main bearing type: CARB, TRB or SRB
    turbine.nacelle.mb2Type = 'SRB'  # (Str): Second bearing type: CARB, TRB or SRB
    turbine.nacelle.yaw_motors_number = 8.0  # (Float): number of yaw motors
    turbine.nacelle.uptower_transformer = True
    turbine.nacelle.flange_length = 0.5 #m
    turbine.nacelle.gearbox_cm = 0.1
    turbine.nacelle.hss_length = 1.5
    turbine.nacelle.overhang = 5.0 #TODO - should come from turbine configuration level

    turbine.nacelle.check_fatigue = 0 #0 if no fatigue check, 1 if parameterized fatigue check, 2 if known loads inputs

    # TODO: should come from rotor (these are FAST outputs)
    turbine.nacelle.DrivetrainEfficiency = 0.95
    turbine.nacelle.rotor_bending_moment_x = 330770.0# Nm
    turbine.nacelle.rotor_bending_moment_y = -16665000.0 # Nm
    turbine.nacelle.rotor_bending_moment_z = 2896300.0 # Nm
    turbine.nacelle.rotor_force_x = 599610.0 # N
    turbine.nacelle.rotor_force_y = 186780.0 # N
    turbine.nacelle.rotor_force_z = -842710.0 # N'''

    #turbine.nacelle.h0_rear = 1.35 # only used in drive smooth
    #turbine.nacelle.h0_front = 1.7

    # =================

    # leftover variable
    turbine.generator_speed = 1173.7  # (Float, rpm)  # generator speed


    # === run ===
    turbine.run()
    print 'mass rotor blades (kg) =', turbine.rotor.mass_all_blades
    print 'mass hub system (kg) =', turbine.hubSystem.hub_system_mass
    print 'mass nacelle (kg) =', turbine.nacelle.nacelle_mass
    print 'mass tower (kg) =', turbine.tower.mass
    print 'maximum tip deflection (m) =', turbine.maxdeflection.max_tip_deflection
    print 'ground clearance (m) =', turbine.maxdeflection.ground_clearance
    # print
    # print '"Torque":',turbine.nacelle.rotor_torque
    # print 'Mx:',turbine.nacelle.rotor_bending_moment_x
    # print 'My:',turbine.nacelle.rotor_bending_moment_y
    # print 'Mz:',turbine.nacelle.rotor_bending_moment_z
    # print 'Fx:',turbine.nacelle.rotor_force_x
    # print 'Fy:',turbine.nacelle.rotor_force_y
    # print 'Fz:',turbine.nacelle.rotor_force_z
    # =================