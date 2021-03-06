$(function() {
	countryList = null, countries = [];
	withCountries = function(todo) {
		if (countryList === null) {
			$.getJSON("/countries", function(countryRecs) {
				countryList = countryRecs;
				countries = Array(countryList.length + 1);
				for (j = 0; j < countryList.length; j++) {
					countries[countryList[j].Id] = countryList[j]
				};
				if (todo) {
					todo()
				};
			});
		}
		else {
			if (todo) {
				todo()
			}
		};
	};

	countryTemplate = function(value, item) {
		var country = countries && countries[value] || {
				Code: '?',
				Flag_Image: ''
			},
			flag = $('<span class="flagimage">').html(country.Flag_Image);
		return $('<span class="countrypair">').text(country.Code).append(flag);
	};

	makeFilter = function(filterItem, fieldDescriptions) {
		return function(item) { // Create a function to filter items based on
			var keep = true; // user's filter parameters and field types
			for (field in fieldDescriptions) {
				var fd = fieldDescriptions[field];
				if (filterItem[fd.name] && ( // Only check visible fields
						!fd.hasOwnProperty("visible") || fd.visible)) {
					if ((["number", "checkbox", "select"].indexOf(fd.type) > -1 &&
							item[fd.name] != filterItem[fd.name]) ||
						(fd.type == "text" && item[fd.name] &&
							item[fd.name].toLowerCase().indexOf(
								filterItem[fd.name].toLowerCase()) == -1)) {
						keep = false;
						break; // Once a filter fails, quit loop
					}
				}
			};
			return keep
		}
	};

	function postItemChange(jsonURL, item, deferred) {
		$.post(jsonURL, {
				item: JSON.stringify(item)
			},
			function(resp) {
				if (resp.status != 0) {
					$.notify(resp.message)
					deferred.reject(resp.item);
				}
				else {
					deferred.resolve(resp.item);
				}
			}, "json").fail(function(jqXHR, textStatus, errorThrown) {
			$.notify('Posting change failed. ' + textStatus + ' ' + errorThrown);
			deferred.reject(textStatus);
		});
	};

	/* Create a controller object for jsGrid widgets. The jsonURL should
	   accept GET requests to get all the data, and POST requests to insert,
	   update, and delete individual row items.  If inputData is provided,
	   the GET request is skipped and the data array is loaded. When inserting
	   row items, the item Id will be set to 0.  When deleting row items,
	   the item Id will be set to the negative of the Id in the item record.
	 */
	makeController = function(jsonURL, fieldDescriptions, inputData) {
		return {
			loadData: function(filterItem) {
				if (inputData) {
					return inputData.filter(makeFilter(filterItem, fieldDescriptions));
				}
				else {
					var d = $.Deferred();
					$.ajax({
						url: jsonURL,
						dataType: "json"
					}).done(
						function(loadData) { // Return has status = 0 for success
							if (loadData.status != 0) {
								$.notify(loadData.message);
								d.reject();
							}
							else {
								var items = loadData.data.filter(
									makeFilter(filterItem, fieldDescriptions));
								d.resolve(items)
							}
						});
				}
				return d.promise();
			},
			insertItem: function(item) {
				var d = $.Deferred();
				item.Id = 0; // Insert POSTs new item with ID == 0
				postItemChange(jsonURL, item, d);
				return d.promise();
			},
			updateItem: function(item) {
				var d = $.Deferred(); // Update POSTs modified item (same ID)
				postItemChange(jsonURL, item, d);
				return d.promise();
			},
			deleteItem: function(item) {
				var d = $.Deferred(); // Delete POSTs item with negative ID
				if (item.Id) {
					item.Id = -item.Id
				};
				postItemChange(jsonURL, item, d);
				return d.promise();
			},
		};
	};

	playerStatLinkTemplate = function(value, item) {
		return $('<a>').attr('href', base + 'playerStats/' + item.Id)
			.text(item.Name)
	};

	playerNameAssociationTemplate = function(value, item) {
		var playerStatLink = $('<a>')
			.attr('href', base + 'playerStats/' + (item.Player || item.Id) +
				'?tournament=' + (item.Tournament || 'all'))
			.text(item.Name);
		return $('<span>').text(item.Association ? ' / ' + item.Association : '')
			.prepend(playerStatLink);
	};

	tournamentLinkTemplate = function(value, item) {
		return $('<a>').attr('href', base + 't/' + item.Name + '/tournament')
			.text(item.Name)
	};

	createDuplicateButton = function(item, callback, kind) {
		var name = kind || 'tournament',
			lowericon = $('<span class="duplicate-icon-bl">').text('📄');
		return $('<span class="duplicate-icon-tr jsgrid-button" title="Duplicate ' + name + '">')
			.data(name + 'id', item.Id).text('📄')
			.append(lowericon).on('click', callback)
	};

	copyObj = function(obj, template, exclude) {
		var result = new Object();
		for (field in (template || obj)) {
			if (exclude === undefined || !(field in exclude)) {
				result[field] = obj[field]
			}
		};
		return result
	};

	clearObject = function(obj) {
		for (attr in obj) {
			delete obj[attr]
		}
	};

});
