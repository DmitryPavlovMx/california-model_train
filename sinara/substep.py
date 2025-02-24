import os

from datetime import datetime
from pathlib import Path

import git
import glob
import shutil
import dataclasses
import inspect
import pprint
import json
import atexit
import sys, traceback

from IPython.core.display import Markdown, display

from .fs import SinaraFileSystem
from .settings import _SinaraSettings
from ._version import __version__

import logging

def get_sinara_version():
    return __version__

def get_sinara_server_image_name():
    return os.getenv("JUPYTER_IMAGE_SPEC", "UNKNOWN")

class StopExecution(Exception):
    pass

def isnotebook():
    try:
        shell = get_ipython().__class__.__name__
        if shell == 'ZMQInteractiveShell':
            # if "SNR_IS_NOTEBOOK" not in os.environ:
            #     os.environ["SNR_IS_NOTEBOOK"] = "True"
            return True   # Jupyter notebook or qtconsole
        elif shell == 'TerminalInteractiveShell':
            return False  # Terminal running IPython
        else:
            return False  # Other type (?)
    except NameError:
        return False      # Probably standard Python interpreter

def set_curr_notebook_name(nb_name):
    os.environ["DSML_CURR_NOTEBOOK_NAME"] = nb_name
    
def get_curr_notebook_name():
    return os.getenv('DSML_CURR_NOTEBOOK_NAME') or "standalone"

def set_curr_notebook_output_name(nb_name):
    os.environ["DSML_CURR_NOTEBOOK_OUTPUT_NAME"] = nb_name

def get_curr_notebook_output_name():
    return os.getenv('DSML_CURR_NOTEBOOK_OUTPUT_NAME') or "standalone"

def get_sinara_user_work_dir():
    nb_user = os.getenv("NB_USER") or "jovyan"
    return os.getenv("JUPYTER_SERVER_ROOT") or f"/home/{nb_user}/work"

def get_sinara_step_tmp_path():
    return f"{os.getcwd()}/tmp"

def get_sinara_platform():
    return os.getenv("SINARA_PLATFORM")
    
def get_tmp_work_path(write_root=False):
    get_tmp_prepared()
    valid_tmp_target_path = f'/tmp/step{os.getcwd().replace(get_sinara_user_work_dir(),"")}'
    if write_root:
        return valid_tmp_target_path
    else:
        valid_tmp_target_path_runid = f'{valid_tmp_target_path}/{get_curr_run_id()}'
        os.makedirs(valid_tmp_target_path_runid, exist_ok=True)
        return valid_tmp_target_path_runid
    
def get_tmp_prepared():
    if "DSML_CURR_RUN_ID_FROM_PLINE" not in os.environ:
        valid_tmp_target_path = f'/tmp/step{os.getcwd().replace(get_sinara_user_work_dir(),"")}'
        os.makedirs(valid_tmp_target_path, exist_ok=True)
        tmp_path = Path('./tmp')
        if tmp_path.is_symlink():
            tmp_link = tmp_path.readlink()
            if tmp_link.as_posix() != valid_tmp_target_path:
                print("'tmp' dir is not valid, creating valid tmp dir...")
                tmp_path.unlink()                
                os.symlink(valid_tmp_target_path, './tmp', target_is_directory=True)
        else:
            if tmp_path.exists():
                print('\033[1m' + 'Current \'tmp\' folder inside your component is going to be deleted. It\'s safe, as \'tmp\' is moving to cache and will be recreated again.' + '\033[0m')
                shutil.rmtree(tmp_path)

            os.symlink(valid_tmp_target_path, './tmp', target_is_directory=True)
    else:
        tmp_path = Path('./tmp')
        if tmp_path.is_symlink():
            tmp_path.unlink()
        else:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
        
        os.makedirs(get_sinara_step_tmp_path())


def print_line_as_bold(str):
    if isnotebook():
        display(Markdown(f"**{str}**\n"))
    else:
        print(str)

 
def ipynb_to_html(src_path, dst_path):
    
    import nbformat
    from nbconvert import HTMLExporter

    # read source notebook
    with open(src_path) as f:
        nb = nbformat.read(f, as_version=4)
    
    # export to html
    html_exporter = HTMLExporter()
    html_data, resources = html_exporter.from_notebook_node(nb)

    # write to output file
    with open(dst_path, "w") as f:
        f.write(html_data)

start_time = datetime.now()
pp = pprint.PrettyPrinter()

def get_curr_run_id():
    if "DSML_CURR_RUN_ID" not in os.environ:
        run_id = reset_curr_run_id()
    else:
        run_id = os.environ["DSML_CURR_RUN_ID"]
    return run_id

def get_sinara_step_tmp_path():
    return f"{os.getcwd()}/tmp"

def reset_curr_run_id():
    from datetime import datetime
    run_id = f"run-{datetime.now().strftime('%y-%m-%d-%H%M%S')}"
    # When sinara_component is running in Kubernetes CronJob
    if "DSML_CURR_RUN_ID_FROM_PLINE" in os.environ:
        run_id = os.environ["DSML_CURR_RUN_ID_FROM_PLINE"]
    os.environ["DSML_CURR_RUN_ID"] = run_id
    return run_id


ENV_NAME = 'ENV_NAME'
PIPELINE_NAME = 'PIPELINE_NAME'
ZONE_NAME = 'ZONE_NAME'
STEP_NAME = 'STEP_NAME'
RUN_ID = 'RUN_ID'
ENTITY_NAME = 'ENTITY_NAME'
ENTITY_PATH = 'ENTITY_PATH'
SUBSTEP_NAME = 'SUBSTEP_NAME'

class NotebookSubstepRunResult:
    """DSML module must set DSMLModule.run_result property
    on the completion of work using DSMLModuleRunResult value.
    By defaul DSMLModule.run_result is set into UNKNOWN value"""
    
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclasses.dataclass(frozen=True)
class DSMLUrls:
    """
    DSMLUrls is base class for objects that contain URLs of Data Entities
    DSMLUrls objects are created via methods of DSMLModule 
    """
        
    def fullname(self, entity_name):
        full_entity_name = f'full_{entity_name}'
        return getattr(self, full_entity_name)

def get_pipeline_params(*, pprint=False):
    """Get pipeline params

    Args:
        pprint (bool, optional): Print pipeline params. Defaults to False.

    Raises:
        Exception: If pipeline_name is not defined in params

    Returns:
        dict: pipepline params dictionary
    """
    params_file_name = "params/step_params.json"
    
    if "SINARA_STEP_PARAMS_FILE_PATH" in os.environ:
        params_file_name = os.environ["SINARA_STEP_PARAMS_FILE_PATH"]
    
    if "SINARA_PIPELINE_PARAMS_FILE_PATH" in os.environ:
        params_file_name = os.environ["SINARA_PIPELINE_PARAMS_FILE_PATH"] or params_file_name
  
    params = {}
    with open(params_file_name) as json_file:
       params = json.load(json_file)
    
    pipeline_params = params["pipeline_params"]
    if "SINARA_STEP_ENV_NAME" in os.environ:
        pipeline_params["env_name"] = os.environ["SINARA_STEP_ENV_NAME"]
    
    if not pipeline_params.get("pipeline_name"):
            raise Exception(f"In the file {params_file_name} 'pipeline_name' param is not defined. It's mandatory. ")
    
    if pprint:
        print_line_as_bold("Pipeline params:")
        pp.pprint(pipeline_params)
        print("\n")

    return pipeline_params

def get_step_params(*, pprint=False):
    """Get step params

    Args:
        pprint (bool, optional): Print step params. Defaults to False.

    Returns:
        dict: step params dictionary
    """
    params_file_name = "params/step_params.json"
    if "SINARA_STEP_PARAMS_FILE_PATH" in os.environ:
        params_file_name = os.environ["SINARA_STEP_PARAMS_FILE_PATH"]
    
    params = {}
    with open(params_file_name) as json_file:
       params = json.load(json_file)
    
    step_params = params["step_params"]
    
    if pprint:
        print_line_as_bold("Step params:")
        pp.pprint(step_params)
        print("\n")
        
    return step_params

def get_user():
    return _SinaraSettings.get_user()

class NotebookSubstep:
    """
    NotebookSubstep instance must be created inside any NotebookSubstep notebook
    NotebookSubstep provides: 
     - functions to define interface of NotebookSubstep
     - functions to work with data cache
     - properties to access NotebookSubstep execution context
    Single instance only of NotebookSubstep allowed inside python kernel
    """
    # single instance only of NotebookSubstep allowed inside python kernel
    _current_module = None
    
    def __init__(self,
                 pipeline_params,
                 step_params,
                 substeps_params):
        """NotebookSubstep constructor"""
        
        get_tmp_prepared()
        
        default_env_name = "user"  # for interactive mode
        #default_pipeline_name = "pipeline" # mandatary in pipeline params
        default_zone_name = "zone" # optional param
        default_step_name = _SinaraSettings.get_default_step_name()
                
        self._pipeline_params = pipeline_params
        self._step_params = step_params
        self._substeps_params = substeps_params
        
        self._run_id = get_curr_run_id()
        self._metrics = {}
        self._metrics["run_id"] = get_curr_run_id()
        self._env_name = pipeline_params.get("env_name") or default_env_name
        self._pipeline_name = pipeline_params.get("pipeline_name") #or default_pipeline_name
        
        if not self._pipeline_name:
            raise Exception("'pipeline_name' must be specified within pipeline_params")
        
        self._zone_name = pipeline_params.get("zone_name") or default_zone_name
        
        step_name = step_params.get("step_name") or default_step_name
        
        if not step_name:
            raise Exception(f"'step_name' param is not defined. It's mandatory. ")

        self._step_name = step_name
        
        self._registered_inputs = []
        self._registered_outputs = []
        self._registered_custom_inputs = []
        self._registered_custom_outputs = []
        self._registered_tmp_inputs = []
        self._registered_tmp_outputs = []
        self._registered_tmp_entities = []
        
        
        
        self.registered_inputs = {}
        
        self.registered_outputs = {}
        
        self.registered_tmp_inputs = {}
        
        self.registered_tmp_outputs = {}
        
        self.registered_tmp_entities = {}


        self._commit = str(git.Repo().commit("HEAD"))
        self._origin = next(git.Repo().remotes.origin.urls)
        git.Repo().git.clear_cache()

        self._run_result = NotebookSubstepRunResult.UNKNOWN


        NotebookSubstep._current_module = self
        
        self._serialize_run(
            get_curr_notebook_name(),
            get_curr_notebook_output_name(),
            f"{datetime.now()}",
            pipeline_params,
            step_params,
            substeps_params,
            True)
        
        self.setLoggingLevel('INFO')

    def setLoggingLevel(self, level):
        logging.root.setLevel(level)
        
# The idea of a tool which creates structure of steps in Git. The tool will be in a separate repository
    def get_visualizer_report_name(self):
        import uuid;
        output_guid = str(uuid.uuid4())
        print({self.step_name})
        return f"{self.step_name}.{self.substep_name}.{output_guid}.json"

    def exit_in_visualize_mode(self):
        """
        Stop the notebook for visualizing a pipeline
        """
        if "DESIGN_MODE" not in os.environ:
            pass
        else: 
            step_dirpath = os.getenv("VISUALIZER_SESSION_RUN_ID", "")
            if not step_dirpath:
                raise Exception("VISUALIZER_SESSION_RUN_ID environment variable not set or empty")
            
            os.makedirs(step_dirpath, exist_ok=True)
            
            substep_filename = self.get_visualizer_report_name()
                
            data_inputs = {}
            data_outputs = {}
            
            for _input in self._inputs_for_print:
                data_inputs.update(_input)
                
            for _output in self._outputs_for_print:
                data_outputs.update(_output)
            data = {
                'step_name': self.step_name,
                'substep_name': self.substep_name,
                'inputs': data_inputs,
                'outputs': data_outputs
            }
            
            with open(f'{step_dirpath}/{substep_filename}', 'w') as outfile:
                json.dump(data, outfile)
        
            #try:
            raise StopExecution
            #except:
                  #traceback.print_exc()
            #      sys.exit(0)
    
    def _outputs_url(self):
        """Returns storage path where all output entities are stored"""
        env_path = _SinaraSettings.get_env_path(self._env_name)
        outputs_url = f"{env_path}/{self._pipeline_name}/{self._zone_name}/{self._step_name}/{self._run_id}"
        return outputs_url

    def _output_full_name(self, entity_name):
        """Returns output fullname by name"""
        return f"{self._env_name}.{self._pipeline_name}.{self._zone_name}.{self._step_name}.{entity_name}"
    

    def _component_cache_url(self):
        """Returns local path where managed cached entities are stored for current component"""
        env_path = _SinaraSettings.get_env_path(self._env_name)
        return f"{env_path}/{self._pipeline_name}/{self._zone_name}/{self._step_name}"

    def _cache_url(self):
        """Returns local path where managed cached entities are stored for current run"""
        env_path = _SinaraSettings.get_tmp_path(self._env_name)
        return f"{env_path}/{self._pipeline_name}/{self._zone_name}/{self._step_name}/{self._run_id}"

    def _step_cache_url(self):
        """Returns local path where managed cached entities are stored for current component"""
        env_path = _SinaraSettings.get_tmp_path(self._env_name)
        return f"{env_path}/{self._pipeline_name}/{self._zone_name}/{self._step_name}"
            
    def add_metric(self, metric_name, metric_value):
        """Add Substep metric

        Args:
            metric_name (str): Name of the metric
            metric_value (any): Value of the metric
        """
        self._metrics[metric_name] = metric_value
        
    def print_metrics(self):
        pp.pprint(self._metrics)
    
    def _serialize_run(
            self,
            input_nb_name,
            output_nb_name,
            start_time,
            pipeline_params,
            step_params,
            substeps_params,
            intermediate_runinfo = False):
        """Serializes run_info by Step
           'intermediate_runinfo' parameter is for an intermediate run_info serialization
           Run result for intermediate_runinfo can be not set as 'SUCCESS'
        """
        #self._register_output_url(f"reports.{get_curr_notebook_name()}")

        start_time = datetime.fromisoformat(start_time)
        stop_time = datetime.now()
        if not intermediate_runinfo:
            self._run_result = NotebookSubstepRunResult.SUCCESS
            
        run_info = self._get_runinfo()
        run_info["input_nb_name"] = input_nb_name
        run_info["output_nb_name"] = output_nb_name

        # you can check if paremeters/run_paremeters were changed via sinara module run
        # by comparison run_info saved using serialize run and run_info saved via _save_runinfo
        # TODO: it makes sence to raise exception if parameters or run_parameters were changed
        run_info["pipeline_params"] = pipeline_params
        run_info["step_params"] = step_params
        run_info["substeps_params"] = substeps_params
        run_info["sinara_version"] = get_sinara_version()
        run_info["sinara_server_image"] = get_sinara_server_image_name()

        run_info["start_time"] = f"{start_time}"
        run_info["stop_time"] = f"{stop_time}"
        run_info["status"] = 'COMPLETE'
        run_info["duration"] = f"{stop_time - start_time}"

        run_info["commit"] = self._commit
        
        run_info["outputs_url"] = self._outputs_url()
        run_info["notebook_report_url"] = self.make_data_url(self._step_name, self._env_name, self._pipeline_name, self._zone_name, f"reports.{get_curr_notebook_name()}", self._run_id, 'outputs')
        
        otput_nb_stem = Path(output_nb_name).stem
        run_info_file_name = f"tmp/{otput_nb_stem}.runinfo.json"

        with open(run_info_file_name, 'w') as outfile:
            json.dump(run_info, outfile)
        
        metric_file_name = f"tmp/{otput_nb_stem}.metrics.json"
        with open(metric_file_name, 'w') as outfile:
            json.dump(self.metrics, outfile)

    def _get_runinfo(self):
        """Returns current run_info"""
        global start_time
        run_info = {}
        stop_time = datetime.now()
        run_info["start_time"] = f"{start_time}"
        run_info["stop_time"] = f"{stop_time}"
        run_info["result"] = self._run_result
        run_info["pipeline_params"] = self._pipeline_params
        run_info["step_params"] = self._step_params
        run_info["substeps_params"] = self._substeps_params
        run_info["inputs"] = self.registered_inputs
        run_info["outputs"] = self.registered_outputs
        run_info["tmp"] = {**self.registered_tmp_inputs, **self.registered_tmp_outputs, **self.registered_tmp_entities}
        run_info["status"] = 'RUNNING'
        run_info["duration"] = f"{stop_time - start_time}"
        run_info["origin"] = self._origin
        run_info["step_name"] = self._step_name

        return run_info

    def interface(self, *,
                  inputs=[],
                  outputs=[],
                  custom_inputs=[],
                  custom_outputs=[],
                  tmp_inputs=[],
                  tmp_outputs=[],
                  tmp_entities=[]
                 ):
        """Setup substep interface

        Args:
            inputs (list, optional): Substep input entities. Defaults to [].
            outputs (list, optional): Substep output entities. Defaults to [].
            custom_inputs (list, optional): Substep custom input entities. Defaults to [].
            custom_outputs (list, optional): Substep custom output entities. Defaults to [].
            tmp_inputs (list, optional): Substep temporary input entities. Defaults to [].
            tmp_outputs (list, optional): Substep temporary output entities. Defaults to [].
            tmp_entities (list, optional): Substep custom temporary entities. Defaults to [].
        """
        
        self._registered_inputs = self._get_validated_interface_data(inputs,
                                                                     required_keys=[STEP_NAME,
                                                                                    ENTITY_NAME],
                                                                     available_keys=[STEP_NAME,
                                                                                     ENTITY_NAME,
                                                                                     ENV_NAME,
                                                                                     PIPELINE_NAME,
                                                                                     ZONE_NAME,
                                                                                     RUN_ID],
                                                                     )
        
        self._inputs_for_print = [self.get_entity_for_print(entity, 'inputs') for entity in self._registered_inputs]
        
        #pp.pprint(self._inputs_for_print)
        
        self._registered_outputs = self._get_validated_interface_data(outputs,
                                                                     required_keys=[ENTITY_NAME],
                                                                     available_keys=[ENTITY_NAME])
        
        self._outputs_for_print = [self.get_entity_for_print(entity, 'outputs') for entity in self._registered_outputs]
        
        self._registered_custom_inputs = self._get_validated_interface_data(custom_inputs,
                                                                     required_keys=[ENTITY_NAME,
                                                                                    ENTITY_PATH],
                                                                     available_keys=[ENTITY_NAME,
                                                                                     ENTITY_PATH])
        
        self._custom_inputs_for_print = [self.get_entity_for_print(entity, 'custom_inputs') for entity in self._registered_custom_inputs]
        
        self._registered_custom_outputs = self._get_validated_interface_data(custom_outputs,
                                                                             required_keys=[ENTITY_NAME,
                                                                                            ENTITY_PATH],
                                                                             available_keys=[ENTITY_NAME,
                                                                                            ENTITY_PATH])
        
        self._custom_outputs_for_print = [self.get_entity_for_print(entity, 'custom_outputs') for entity in self._registered_custom_outputs]
        
        self._registered_tmp_inputs = self._get_validated_interface_data(tmp_inputs,
                                                                         required_keys=[ENTITY_NAME],
                                                                         available_keys=[ENTITY_NAME])
        
        self._tmp_inputs_for_print = [self.get_entity_for_print(entity,'tmp_inputs') for entity in self._registered_tmp_inputs]
        
        
        self._registered_tmp_outputs = self._get_validated_interface_data(tmp_outputs,
                                                                          required_keys=[ENTITY_NAME],
                                                                          available_keys=[ENTITY_NAME])
        
        self._tmp_outputs_for_print = [self.get_entity_for_print(entity, 'tmp_outputs') for entity in self._registered_tmp_outputs]
        
        
        self._registered_tmp_entities = self._get_validated_interface_data(tmp_entities,
                                                                          required_keys=[ENTITY_NAME],
                                                                          available_keys=[ENTITY_NAME])
        
        self._tmp_entities_for_print = [self.get_entity_for_print(entity, 'tmp_entities') for entity in self._registered_tmp_entities]
        
        
        
    def print_interface_info(self):
        """Prints step name, inputs, outputs, tmp urls and cache usage info"""
        
        print_line_as_bold("STEP NAME:")
        pp.pprint(self.step_name)
        print("\n")
        
        if self._inputs_for_print:
            print_line_as_bold("INPUTS:")
            pp.pprint(self._inputs_for_print)
            print("\n")
        
        if self._outputs_for_print: 
            print_line_as_bold("OUTPUTS:")
            pp.pprint(self._outputs_for_print)
            print("\n")
        
        if self._custom_inputs_for_print: 
            print_line_as_bold("CUSTOM INPUTS:")
            pp.pprint(self._custom_inputs_for_print)
            print("\n")
        
        if self._custom_outputs_for_print: 
            print_line_as_bold("CUSTOM OUTPUTS:")
            pp.pprint(self._custom_outputs_for_print)
            print("\n")
        
        if self._tmp_inputs_for_print: 
            print_line_as_bold("TMP INPUTS:")
            pp.pprint(self._tmp_inputs_for_print)
            print("\n")
   
        if self._tmp_outputs_for_print: 
            print_line_as_bold("TMP OUTPUTS:")
            pp.pprint(self._tmp_outputs_for_print)
            print("\n")
            
        if self._tmp_entities_for_print: 
            print_line_as_bold("TMP ENTITIES:")
            pp.pprint(self._tmp_entities_for_print)
            print("\n")
    
    @property
    def metrics(self):
        """ Supstep metrics

        Returns:
            dict: Supstep metrics
        """
        return self._metrics.copy()
    
    @property
    def env_name(self):
        """ Substep environment name

        Returns:
            str: Name of the current environment
        """
        return self._env_name

    @property
    def pipeline_name(self):
        """ Name of the pipeline substep belongs to

        Returns:
            str: Pipeline name
        """
        return self._pipeline_name

    @property
    def zone_name(self):
        """Name of the zone substep belongs to

        Returns:
            str: Zone name
        """
        return self._zone_name

    @property
    def step_name(self):
        """Name of the step which current substep belongs to

        Returns:
            str: Step name
        """
        return self._step_name

    @property
    def run_id(self):
        """Current run id of the step

        Returns:
            str: Run id
        """
        return self._run_id
        
    @property
    def substep_name(self):
        """Current substep name

        Raises:
            Exception: if env variable DSML_CURR_NOTEBOOK_NAME is not set while running substep

        Returns:
            str: Substep name
        """
        if "DSML_CURR_NOTEBOOK_NAME" in os.environ:
            substep_notebook_name = os.getenv("DSML_CURR_NOTEBOOK_NAME")
            self._substep_name = substep_notebook_name.split('.')[0]
        else:
           raise Exception('Internal error')
        return self._substep_name
    
    def _last_run_id_from_fs(self, entity_name, step_path):

        if "DESIGN_MODE" in os.environ:
            return entity_name
        
        fs = SinaraFileSystem.FileSystem()

        entity_paths = fs.glob(f"{step_path}/*/{entity_name}/_SUCCESS")

        run_ids = sorted([entity_path.split("/")[-3] for entity_path in entity_paths])

        if len(run_ids) > 0:
            return run_ids[-1]
        else:
            return None

    def last_run_id(self, step_name, env_name, pipeline_name, zone_name, entity_name):
        """ Get the last run id stored on FS.
            Provide argument values to filter and search the run id

        Args:
            step_name (str): Name of the step\n
            env_name (str): Environment name\n
            pipeline_name (str): Pipeline name\n
            zone_name (str): Zone name\n
            entity_name (str): Entity name\n

        Raises:
            Exception: If no run ids found for provided arguments (entity)

        Returns:
            str: last run id
        """
        env_path = _SinaraSettings.get_env_path(env_name)
        
        #print(env_path)
        
        step_path = f"{env_path}/{pipeline_name}/{zone_name}/{step_name}"
        #print(step_path)

        last_run_id_from_fs = self._last_run_id_from_fs(entity_name, step_path)

        if last_run_id_from_fs is None:
            raise Exception(
                f"There is no successfully created entity for path: '{step_path}/*/{entity_name}' ")
        return last_run_id_from_fs

    def make_data_url(self, step_name, env_name, pipeline_name, zone_name, entity_name, run_id, data_type):
        self._validate_entity_name(entity_name)
        
        entity_name = entity_name.replace(".", "_")

        entity_full_name = self._get_entity_full_name(step_name, env_name, pipeline_name, zone_name, entity_name)

     
        env_path = _SinaraSettings.get_env_path(env_name)
        entity_url = f"{env_path}/{pipeline_name}/{zone_name}/{step_name}/{run_id}/{entity_name}"
        
        if data_type == 'inputs':

            self.registered_inputs[entity_full_name] = entity_url
            
        elif data_type == 'outputs':
            
            self.registered_outputs[entity_full_name] = entity_url
        
        elif data_type == 'tmp_inputs' or data_type == 'tmp_outputs':
            
            self.registered_tmp_io[f'tmp:{entity_full_name}'] = entity_url

        return entity_url, entity_full_name

    def make_custom_data_url(self, entity, data_type):
        
        entity_url = entity.get(ENTITY_PATH)
        entity_name = entity.get(ENTITY_NAME)
        
        if data_type == 'custom_inputs':

            self.registered_inputs[entity_name] = entity_url
            
        elif data_type == 'custom_outputs':
            
            self.registered_outputs[entity_name] = entity_url

        return entity_url

    
    def make_tmp_output_url(self, entity_name):
        """Registers new cache entity and returns URL for it"""
        # Here we create run-id directory only because,
        # user are supposed to create either file or folder as an entity.
        self._validate_entity_name(entity_name)
        entity_full_name = f"tmp:{self._output_full_name(entity_name)}"
        entity_url = f"{self._cache_url()}/{entity_name}"
        try:
            os.makedirs(entity_url)
        except:
            pass
        
        self.registered_tmp_outputs[entity_full_name] = entity_url
        return entity_url
    
    def _get_tmp_input_url(self, entity_name):
        """Find last run for tmp entity and return it's url"""
        self._validate_entity_name(entity_name)

        entity_paths = glob.glob(f"{self._step_cache_url()}/*/{entity_name}")

        run_ids = sorted([entity_path.split("/")[-2] for entity_path in entity_paths])

        if len(run_ids) > 0:
            last_run_id = run_ids[-1]
        else:
            raise Exception(f"There is no an entity for path: '{self._step_cache_url()}/*/{entity_name}' ")

        entity_url = f"{self._step_cache_url()}/{last_run_id}/{entity_name}"
        return entity_url

    def make_tmp_input_url(self, entity_name):
        """Registers existed cache entity and returns URL for it """
        entity_url = self._get_tmp_input_url(entity_name)
        entity_full_name = f"tmp:{self._output_full_name(entity_name)}"
        self.registered_tmp_inputs[entity_full_name] = entity_url
        return entity_url
    
    def _get_entity_full_name(self, step_name, env_name, pipeline_name, zone_name, entity_name):
        return f"{env_name}.{pipeline_name}.{zone_name}.{step_name}.{entity_name}"

    def get_entity_for_print(self, entity, data_type):
        
        entity_name = entity.get(ENTITY_NAME)
        step_name = self._step_name
        env_name = self._env_name
        pipeline_name = self._pipeline_name
        zone_name = self._zone_name
        run_id = self._run_id
        
        self._validate_entity_name(entity_name)
        
        entity_name = entity_name.replace(".", "_")

        entity_full_name = self._get_entity_full_name(step_name, env_name, pipeline_name, zone_name, entity_name)
     
        env_path = _SinaraSettings.get_env_path(env_name)
        entity_url = f"{env_path}/{pipeline_name}/{zone_name}/{step_name}/{run_id}/{entity_name}"
        
        if data_type == 'inputs':
            step_name = entity.get(STEP_NAME) if entity.get(STEP_NAME) else self.step_name
            pipeline_name = entity.get(PIPELINE_NAME) if entity.get(PIPELINE_NAME) else self.pipeline_name
            env_name =  entity.get(ENV_NAME) if entity.get(ENV_NAME) else self.env_name
            zone_name = entity.get(ZONE_NAME) if entity.get(ZONE_NAME) else self.zone_name
            run_id = entity.get(RUN_ID) if entity.get(RUN_ID) else self.last_run_id(step_name, env_name, pipeline_name, zone_name, entity_name)
            
            entity_full_name = self._get_entity_full_name(step_name, env_name, pipeline_name, zone_name, entity_name)
     
            env_path = _SinaraSettings.get_env_path(env_name)
            entity_url = f"{env_path}/{pipeline_name}/{zone_name}/{step_name}/{run_id}/{entity_name}"
        

            return {entity_full_name: entity_url}
            
        elif data_type == 'outputs':
            
            pipeline_name = entity.get(PIPELINE_NAME) if entity.get(PIPELINE_NAME) else self.pipeline_name
            env_name = entity.get(ENV_NAME) if entity.get(ENV_NAME) else self.env_name
            zone_name = entity.get(ZONE_NAME) if entity.get(ZONE_NAME) else self.zone_name
            
            entity_full_name = self._get_entity_full_name(step_name, env_name, pipeline_name, zone_name, entity_name)
     
            env_path = _SinaraSettings.get_env_path(env_name)
            entity_url = f"{env_path}/{pipeline_name}/{zone_name}/{step_name}/{run_id}/{entity_name}"
        
            return {entity_full_name: entity_url }
        
        elif data_type == 'custom_inputs':
            entity_url = entity.get(ENTITY_PATH, None)

            return {entity_name: entity_url}
            
        elif data_type == 'custom_outputs':
            entity_url = entity.get(ENTITY_PATH, None)
            return {entity_name: entity_url}
        
        elif data_type == 'tmp_inputs':
            entity_url = self._get_tmp_input_url(entity_name)
            return {f'tmp:{entity_full_name}': entity_url }
           
        elif data_type == 'tmp_outputs':
            entity_url = f"{self._cache_url()}/{entity_name}"
            return {f'tmp:{entity_full_name}': entity_url }

        elif data_type == 'tmp_entities':
            entity_url = f"{self._cache_url()}/{entity_name}"
            return {f'tmp:{entity_full_name}': entity_url }

        
    def _validate_entity_name(self, entity_name):
        """Checks allowed symbols of entity name and raise exeption for non-valid name"""
        if entity_name.find('/') != -1:
            raise Exception("Entity name can't contain '/' character")
    
    def _get_validated_interface_data(self, data, *, required_keys, available_keys):
        """
        TODO:
        Should be required && available
        Add parameters description
        Add example from  full step notebook
        """
        if data:
            for required_key in required_keys:
                for data_item in data:
                    if required_key not in data_item.keys():
                        raise Exception(f"Mandatory key '{required_key}' isn't defined in {data_item}. Required keys are {available_keys}")

            for data_item in data:
                for key, value in data_item.items():
                    if key not in available_keys:
                        raise Exception(f"This key '{key}' in '{data_item}' isn't permitted. Available keys are {available_keys}")
        return data

    def inputs(self, *, step_name, env_name="curr_env_name", pipeline_name="curr_pipeline_name", zone_name="curr_zone_name", run_id="last_run_id"):
        """ Substep Inputs

        Args:
            step_name (str): Name of the step
            env_name (str, optional): Name of the environment. Defaults to "curr_env_name".
            pipeline_name (str, optional): Name of the pipeline. Defaults to "curr_pipeline_name".
            zone_name (str, optional): Name of the zone. Defaults to "curr_zone_name".
            run_id (str, optional): Specific run id to get. Defaults to "last_run_id".

        Raises:
            Exception: If the are multiple steps in different zones and zone ambiguity cannot be resolved

        Returns:
            dict: Substep inputs
        """
        registered_inputs_info = []
        
        filtered_inputs = []
        
        is_set_filter_by_env_name = (env_name != "curr_env_name")
        is_set_filter_by_pipeline_name = (pipeline_name != "curr_pipeline_name")
        is_set_filter_by_zone_name = (zone_name != "curr_zone_name")
        is_set_filter_by_run_id = (run_id != "last_run_id")

        prev_input_zone_name = ''
        steps_in_diff_zones = 0
        
        current_env_name = env_name if is_set_filter_by_env_name else self.env_name
        current_pipeline_name = pipeline_name if is_set_filter_by_pipeline_name else self.pipeline_name
        current_zone_name = zone_name if is_set_filter_by_zone_name else self.zone_name
        
        for _input in self._registered_inputs:    
            input_env_name = _input.get(ENV_NAME, current_env_name)
            if not _input.get(ENV_NAME):
                _input[ENV_NAME] = input_env_name
                
            input_pipeline_name = _input.get(PIPELINE_NAME, current_pipeline_name)
            
            if not _input.get(PIPELINE_NAME):
                _input[PIPELINE_NAME] = input_pipeline_name
            
            
            input_zone_name = _input.get(ZONE_NAME, current_zone_name)
            
            if not _input.get(ZONE_NAME):
                _input[ZONE_NAME] = input_zone_name
                    
            input_of_step_name = (_input[STEP_NAME] == step_name)
            
            if input_of_step_name:
                
                if prev_input_zone_name != input_zone_name:                
                    steps_in_diff_zones += 1

                if not (is_set_filter_by_env_name or is_set_filter_by_pipeline_name or is_set_filter_by_zone_name):
                    filtered_inputs.append(_input)
                else:

                    input_matched_filter_by_env_name = (is_set_filter_by_env_name and input_env_name == env_name)
                    input_matched_filter_by_pipeline_name = (is_set_filter_by_pipeline_name and input_pipeline_name == pipeline_name)
                    input_matched_filter_by_zone_name = (is_set_filter_by_zone_name and input_zone_name == zone_name)

                    if input_matched_filter_by_env_name or input_matched_filter_by_pipeline_name or input_matched_filter_by_zone_name:
                        filtered_inputs.append(_input)

                prev_input_zone_name = input_zone_name
        #print(filtered_inputs)
        
        if steps_in_diff_zones > 1:
            print(f"Trying to resolving steps ambiguity by defaulting to the zone '{current_zone_name}'...")
            
            # Current zone is preferrable in this case
            filtered_inputs[:] = [_input for _input in filtered_inputs if _input.get(ZONE_NAME, current_zone_name) == current_zone_name ]
            
            #print(filtered_inputs)
            
            diff_zones_count = 0
            
            #print(filtered_inputs)
            
            prev_input_zone_name = ''
            for _input in filtered_inputs:
                input_zone_name = _input.get(ZONE_NAME, current_zone_name )
                if input_zone_name != prev_input_zone_name:
                    diff_zones_count += 1
                prev_input_zone_name = input_zone_name
                    
            #print(diff_zones_count)
  
            if diff_zones_count > 1:
                raise Exception("Ambiguity error: There are more than 1 step with the same name in different zones. Please, define additional parameters to resolve the ambiguity ")
            
        if is_set_filter_by_run_id:
            filtered_inputs[:] = [_input for _input in filtered_inputs if _input.get(RUN_ID, '') == run_id ]
    
        for _input in filtered_inputs:
            entity_name = _input.get(ENTITY_NAME)

            env_name = _input.get(ENV_NAME) #env_name if is_set_filter_by_env_name else self.env_name
            pipeline_name = _input.get(PIPELINE_NAME) #pipeline_name if is_set_filter_by_pipeline_name else self.pipeline_name
            zone_name = _input.get(ZONE_NAME) #zone_name if is_set_filter_by_zone_name else self.zone_name 
            entity_run_id = run_id if run_id != "last_run_id" else self.last_run_id(step_name, env_name, pipeline_name, zone_name, entity_name)


            entity_url, entity_fullname = self.make_data_url(step_name, env_name, pipeline_name, zone_name, entity_name, entity_run_id, 'inputs')

            registered_inputs_info.append((f'full_{entity_name}', str, dataclasses.field(default=entity_fullname)))
            registered_inputs_info.append((entity_name, str, dataclasses.field(default=entity_url)))

        # python allows different classes with the same name
        registered_inputs = dataclasses.make_dataclass('InputUrls',
                                                        registered_inputs_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_inputs
            
    def outputs(self, *, env_name="curr_env_name", pipeline_name="curr_pipeline_name", zone_name="curr_zone_name"):     
        """Substep outputs

        Args:
            env_name (str, optional): Name of the environment. Defaults to "curr_env_name".
            pipeline_name (str, optional): Name of the pipeline. Defaults to "curr_pipeline_name".
            zone_name (str, optional): Name of the zone. Defaults to "curr_zone_name".

        Returns:
            dict: Substep outputs
        """
        registered_outputs_info = []
        
        for _output in self._registered_outputs:
            step_name = self._step_name
            entity_name = _output.get(ENTITY_NAME, None)
            pipeline_name = pipeline_name if pipeline_name != "curr_pipeline_name" else self.pipeline_name
            env_name = env_name if env_name != "curr_env_name" else self.env_name
            zone_name = zone_name if zone_name != "curr_zone_name" else self.zone_name
            run_id = self._run_id
           
            entity_url, entity_fullname = self.make_data_url(step_name, env_name, pipeline_name, zone_name, entity_name, run_id, 'outputs')

            registered_outputs_info.append((f'full_{entity_name}', str, dataclasses.field(default=entity_fullname)))
            registered_outputs_info.append((entity_name, str, dataclasses.field(default=entity_url)))

        # python allows different classes with the same name
        registered_outputs = dataclasses.make_dataclass('OutputUrls',
                                                        registered_outputs_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_outputs

            

    def custom_inputs(self):
        """Substep custom inputs

        Returns:
            dict: Custom inputs
        """
        registered_inputs_info = []
        
        for _input in self._registered_custom_inputs:
            
            entity_name = _input.get(ENTITY_NAME)
            entity_url = self.make_custom_data_url(_input, 'custom_inputs')
            registered_inputs_info.append((entity_name, str, dataclasses.field(default=entity_url)))

        # python allows different classes with the same name
        registered_inputs = dataclasses.make_dataclass('CustomInputUrls',
                                                        registered_inputs_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_inputs

            
    def custom_outputs(self):     
        """Substep custom outputs

        Returns:
            dict: Custom outputs
        """
        registered_outputs_info = []
        
        for _output in self._registered_custom_outputs:
            entity_name = _output.get(ENTITY_NAME)
            entity_url = self.make_custom_data_url(_output, 'custom_outputs')
            registered_outputs_info.append((entity_name, str, dataclasses.field(default=entity_url)))

        # python allows different classes with the same name
        registered_outputs = dataclasses.make_dataclass('CustomOutputUrls',
                                                        registered_outputs_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_outputs
            
            
    def tmp_inputs(self):
        """Substep temporary inputs

        Returns:
            dict: Temporary inputs
        """
        registered_tmp_inputs_info = []
        
        for _tmp_input in self._registered_tmp_inputs:
            
            entity_name = _tmp_input.get(ENTITY_NAME)
            entity_url = self.make_tmp_input_url(entity_name)
            registered_tmp_inputs_info.append((entity_name, str, dataclasses.field(default=entity_url)))
            
        # python allows different classes with the same name
        registered_tmp_inputs = dataclasses.make_dataclass('TmpInputUrls',
                                                        registered_tmp_inputs_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_tmp_inputs

            
    def tmp_outputs(self):
        """Substep temporary outputs

        Returns:
            str: Temporary outputs
        """
        registered_tmp_outputs_info = []
        
        for _tmp_output in self._registered_tmp_outputs:
            
            entity_name = _tmp_output.get(ENTITY_NAME)
            entity_url = self.make_tmp_output_url(entity_name)
            registered_tmp_outputs_info.append((entity_name, str, dataclasses.field(default=entity_url)))
            
        # python allows different classes with the same name
        registered_tmp_outputs = dataclasses.make_dataclass('TmpOutputUrls',
                                                        registered_tmp_outputs_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_tmp_outputs
    
    def tmp_entities(self):
        """Substep temporary entities

        Returns:
            dict: Tempotrary entities
        """
        registered_tmp_entities_info = []
        
        for _tmp_entity in self._registered_tmp_entities:
            
            entity_name = _tmp_entity.get(ENTITY_NAME)
            
            entity_url = self.make_tmp_output_url(entity_name)

            registered_tmp_entities_info.append((entity_name, str, dataclasses.field(default=entity_url)))
            
        # python allows different classes with the same name
        registered_tmp_entities = dataclasses.make_dataclass('TmpEntitiesUrls',
                                                        registered_tmp_entities_info,
                                                    bases=(DSMLUrls,),
                                                    frozen=True)()
        return registered_tmp_entities

    def tensorboard_log_dir(self, log_name):
        """Get log directory where metrics writers for tensorboard
           will write metrics data

        Args:
            log_name (str): Name of the log (experiment)

        Returns:
            str: Log path relative to step folder
        """
        return f"tmp/tensorboard/{self._zone_name}/{log_name}/{self._run_id}"

    def tensorboard_log_base_dir(self, log_name=""):
        """Get log directory for tensorboard where metrics of multiple runs stored

        Args:
            log_name (str, optional): Name of the log (experiment). Defaults to "".

        Returns:
            str: Base log path relative to step folder
        """
        return f"tmp/tensorboard/{self._zone_name}/{log_name}"

    def prepare_tensorbord_logs(self, log_name: str, copy_prev_logs=True, prev_logs_env=None) -> tuple[str, str]:
        """ Prepare tensorboard logs for an experiment, copy previous experiment logs from storage     
        Args:
            log_name (str): Log (Experiment) name, all runs will be placed under this name
            copy_prev_logs (bool, optional): If true, previous experiment logs with name %log_name% will be copied from storage to
                                             current component's tmp folder for easy comparison using tensorboard. Defaults to True.
            prev_logs_env (str, optional): Env name (test, prod, etc) which tells sinara where to look for previous experiment logs on storage. Defaults to None.
    
        Returns:
            tuple[str, str]: 1) Tensorboard log dir which can be used as log_dir argument for tensorboard cli or magic function in a cell
                             2) Log writer dir, which should be used to tell a summary writer where to put current experiment logs
        """
        if copy_prev_logs:
            self.copy_tensorboard_logs_from_store_to_tmp(log_name, prev_logs_env)
        log_writer_dir = self.tensorboard_log_dir(log_name)
        tensorboard_log_dir = self.tensorboard_log_base_dir(log_name)
        print(f"Tensorboard log dir: {tensorboard_log_dir}\nLog writer dir: {log_writer_dir}")
        return tensorboard_log_dir, log_writer_dir

    def copy_tensorboard_logs_from_store_to_tmp(self, log_name="", log_env=None):
        """Copy logs of an experiment from sinara storage to step tmp folder
           
        Args:
            log_name (str, optional): Name of the log (experiment). Defaults to "".
            log_env (_type_, optional): Name of environment of the experiment (log) to copy. Defaults to None.
        """
        fs = SinaraFileSystem.FileSystem()
        tmp_log_dir = self.tensorboard_log_base_dir(log_name)
        env_name = log_env if log_env else self._env_name
        env_path = _SinaraSettings.get_env_path(env_name)
        step_path = f"{env_path}/{self._pipeline_name}/{self._zone_name}/{self._step_name}"
        log_events = fs.glob(f"{step_path}/**/tensorboard/{log_name}/events.out*")
        for log_path in log_events:
            events_file = Path(log_path).name
            run_id = Path(log_path).parts[-4]
            tmp_path = f"{tmp_log_dir}/{run_id}/{events_file}"
            os.makedirs(f"{tmp_log_dir}/{run_id}", exist_ok=True)
            print(f"Copying previous logs from {log_path} to {tmp_path}", flush=True)
            fs.get(log_path, tmp_path)
